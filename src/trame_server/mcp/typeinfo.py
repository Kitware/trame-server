"""What agents see of a class: its properties, methods and constructor.

trame-common and trame-dataclass only store what a class declares, as plain
data (``Cls.mcp_describe()``); this module interprets it. A class is visible
when a keyword or ``mcp_describe()`` declares it, or when it has markers
(``@mcp_method``, ``@mcp_property``), an exposed field or a constructor,
unless it is hidden with False. Fields and constructors come from the
class's ``MCPExposable`` hooks (``_mcp_fields``, ``_mcp_constructor``),
which apply the rules of its type of class, such as a model's
``all_fields``.
"""

from __future__ import annotations

import inspect
import logging
import typing
import weakref
from dataclasses import dataclass, field

from trame_common.decorators.mcp import METHOD_MARKER, PROPERTY_MARKER, mcp_property
from trame_common.obj import mcp as declarations

from trame_server.mcp.schema import (
    check_progress,
    docstring,
    nullable,
    object_class,
    object_classes,
    return_hint,
    type_to_schema,
    unwrap,
)

logger = logging.getLogger("trame_server.mcp")

__all__ = [
    "Constructor",
    "Method",
    "Property",
    "TypeInfo",
    "is_visible",
    "property_schema",
    "reference_schema",
    "tool_reference_schema",
    "type_info",
    "type_name",
    "type_names",
]

STATE_TYPE = "State"


# Methods trame calls back on its own (@change, @trigger, @controller, @watch)
_CALLBACK_MARKERS = (
    "_trame_state_change",
    "_trame_trigger_names",
    "_trame_controller",
    "_watch",
)


@dataclass(frozen=True)
class Property:
    name: str
    origin: str  # "field" (_mcp_fields), "property" (Python) or "state" (key)
    schema: dict  # what is written (objects by id), without its description
    description: str | None = None
    writable: bool = False  # can be written, permissions aside
    requires: tuple = ()  # to read it at all
    set_requires: tuple = ()  # to write it, in addition
    reference: bool = False  # may hold objects agents reach
    type_def: object = None  # the declared type (tuples, objects by id)

    def described(self) -> dict:
        """The schema with the description, as agents read it."""
        if not self.description:
            return dict(self.schema)
        return {**self.schema, "description": self.description}


@dataclass(frozen=True)
class Method:
    name: str  # the name agents call it by
    attr: str
    description: str
    read_only: bool = False
    annotations: dict | None = None  # MCP tool annotations, but readOnlyHint
    concurrent: bool = False
    requires: tuple = ()


@dataclass(frozen=True)
class Constructor:
    attr: str | None  # the classmethod, or None for cls._mcp_build()
    description: str = ""
    requires: tuple = ()
    server: str | None = None  # the classmethod's parameter taking the server


@dataclass(frozen=True)
class TypeInfo:
    cls: type | None  # None for the state object
    visible: bool
    description: str | None = None
    properties: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)
    constructor: Constructor | None = None
    # Why the class's constructor cannot work, warned about when described
    constructor_warning: str | None = None
    # Reference fields left hidden, name -> classes they hold (startup audit)
    hidden_references: dict = field(default_factory=dict)


HIDDEN = TypeInfo(cls=None, visible=False)

# Cached on the class itself (its own __dict__, never inherited): a
# TypeInfo refers to its class, which a WeakKeyDictionary would keep alive
_CACHE_ATTR = "_trame_mcp_type_info"
_VISIBLE = weakref.WeakKeyDictionary()  # cls -> (version, bool)


def type_info(cls) -> TypeInfo:
    """What agents see of ``cls`` (cached until a class declares or is
    described again)."""
    version = declarations.options_version()
    cached = vars(cls).get(_CACHE_ATTR)
    if cached is not None and cached[0] == version:
        return cached[1]
    info = _build(cls) if is_visible(cls) else HIDDEN
    setattr(cls, _CACHE_ATTR, (version, info))
    return info


def is_visible(cls) -> bool:
    """Whether agents may see ``cls``, a component, model or other ``MCPExposable``
    class."""
    if not isinstance(cls, type):
        return False
    version = declarations.options_version()
    cached = _VISIBLE.get(cls)
    if cached is not None and cached[0] == version:
        return cached[1]
    visible = _declares(cls)
    _VISIBLE[cls] = (version, visible)
    return visible


def _declares(cls):
    if object_class(cls) is None:
        return False
    declared = declarations.class_options(cls)["declared"]
    if declared is not None:
        return declared
    # A field's mcp=True is an empty dict of options, which still exposes it
    return (
        declarations.has_markers(cls)
        or any(isinstance(f.options, dict) for f in cls._mcp_fields().values())
        or cls._mcp_constructor() is not None
    )


def _object_reference(annotation, describe):
    """The schema of a value that holds an object of the class ``annotation``. It is
    ``describe(name)`` for a visible class, and a plain string otherwise, since
    agents cannot use the id. None when ``annotation`` names no such class."""
    if typing.get_origin(annotation) is not None:
        return None  # on Python 3.10, isinstance(list[X], type) holds
    cls = object_class(annotation)
    if cls is None:
        return None
    if not is_visible(cls):
        return {"type": "string"}
    return describe(type_name(cls))


def reference_schema(annotation):
    """The ``type_to_schema`` hook that describes a value holding a component or
    model as ``{"object": "T"}``, the same in properties, parameters and returns.
    Agents read it as an ``{"id", "type"}`` reference, a method returns it as
    object_get shows it, and agents write it by id (a parameter also takes an
    object name). ``validate`` checks that it is a string."""
    return _object_reference(annotation, lambda name: {"object": name})


def tool_reference_schema(annotation):
    """The ``type_to_schema`` hook for the input schema of an app's own tool, as
    clients read it in ``tools/list``. An object parameter is a string, and its
    description says what type of object it names."""
    return _object_reference(
        annotation,
        lambda name: {"type": "string", "description": f"{name} object, by id or name"},
    )


# -----------------------------------------------------------------------------
# Type names
# -----------------------------------------------------------------------------

_NAMES = {"version": None, "names": {}, "classes": {}}
_WARNED = weakref.WeakSet()


def type_names():
    """``(names, classes)``: the agent-facing name of every visible class, and
    the reverse. A class is named after itself; when an earlier visible class
    already has that name, it gets its module-qualified name, with a
    warning. ``State`` is the state object's."""
    version = declarations.options_version()
    if _NAMES["version"] == version:
        return _NAMES["names"], _NAMES["classes"]

    names, classes = weakref.WeakKeyDictionary(), weakref.WeakValueDictionary()
    for cls in declarations.declared_classes():
        if not is_visible(cls):
            continue
        name = cls.__name__
        if name in classes or name == STATE_TYPE:
            first = classes.get(name)
            name = f"{cls.__module__}.{cls.__qualname__}"
            if cls not in _WARNED:
                _WARNED.add(cls)
                logger.warning(
                    "Two classes agents see are named %s: %s keeps the name, %s is "
                    "called %s",
                    cls.__name__,
                    "the state object" if first is None else first.__qualname__,
                    cls.__qualname__,
                    name,
                )
        names[cls] = name
        classes[name] = cls
    _NAMES.update(version=version, names=names, classes=classes)
    return names, classes


def type_name(cls) -> str:
    return type_names()[0].get(cls) or cls.__name__


# -----------------------------------------------------------------------------
# Building
# -----------------------------------------------------------------------------


def _members(cls):
    """``{name: member}`` of ``cls`` and its bases, in definition order, a base's
    members first. A member that a subclass overrides keeps the place where the
    base defined it."""
    members = {}
    for klass in reversed(cls.__mro__):
        members.update(vars(klass))
    return members


def _base_names(cls):
    """The names of the members that trame's own base classes define. Those are the
    classes from the packages that the classes in the MRO name in
    ``_mcp_api_packages``. ``all_methods`` never exposes these members, and
    marking or listing one is an error."""
    packages = {"builtins"}
    for klass in cls.__mro__:
        packages.update(vars(klass).get("_mcp_api_packages", ()))
    names = set()
    for klass in cls.__mro__:
        if klass.__module__.split(".")[0] in packages:
            names.update(vars(klass))
    return names


def property_schema(annotation, options, *, ref=None, can_be_null=False):
    """``(schema, description)`` of a property from its annotation and its
    options. The options' ``schema`` keywords go over the annotation's
    schema, which accepts null too with ``can_be_null``. The description is
    the options' own, else the annotation's (``Annotated[T, "..."]``), and
    never stays in the schema."""
    schema = type_to_schema(annotation, ref)
    schema.update(options.get("schema") or {})
    found = schema.pop("description", None)
    if can_be_null:
        schema = nullable(schema)
    return schema, options.get("description") or found


def _build(cls):
    options = declarations.class_options(cls)
    fields = cls._mcp_fields()
    base = _base_names(cls)
    properties, hidden_references = {}, {}

    # Fields (a model's), as the class's _mcp_fields hook exposes them
    for name, f in fields.items():
        opts = f.options
        if not isinstance(opts, dict):
            if opts is None and f.holds_objects:
                hidden_references[name] = object_classes(f.type_def)
            continue
        schema, description = property_schema(
            f.type_def, opts, ref=reference_schema, can_be_null=f.nullable
        )
        properties[name] = Property(
            name=name,
            origin="field",
            schema=schema,
            description=description,
            writable=not opts.get("read_only", False),
            requires=opts.get("requires", ()),
            reference=f.holds_objects,
            type_def=f.type_def,
        )

    # Python properties: marked, or listed
    for attr, member in _members(cls).items():
        if attr in fields:
            continue
        if not isinstance(member, property):
            continue
        marker = (
            getattr(member, PROPERTY_MARKER)
            if isinstance(member, mcp_property)
            else None
        )
        listed = options["properties"].get(attr)
        if listed is False or (marker is None and listed is None):
            continue
        if attr in base:
            msg = f"{cls.__name__}.{attr} is part of trame's API and cannot be exposed"
            raise ValueError(msg)
        opts = {**(marker or {}), **(listed or {})}
        hint = return_hint(member.fget) if member.fget else None
        schema, description = property_schema(hint, opts, ref=reference_schema)
        properties[attr] = Property(
            name=attr,
            origin="property",
            schema=schema,
            description=description or docstring(member.fget),
            writable=member.fset is not None and not opts.get("read_only"),
            requires=opts.get("requires", ()),
            set_requires=opts.get("set_requires", ()),
            reference=bool(object_classes(hint)),
            type_def=hint,
        )

    constructor, warning = _constructor(cls)
    return TypeInfo(
        cls=cls,
        visible=True,
        description=_description(cls, options),
        properties=properties,
        methods=_methods(cls, options, base),
        constructor=constructor,
        constructor_warning=warning,
        hidden_references=hidden_references,
    )


def _description(cls, options):
    """The class's own description option, else its own docstring; neither
    is inherited."""
    if options["description"]:
        return options["description"]
    doc = vars(cls).get("__doc__")
    return unwrap(inspect.cleandoc(doc)) if doc else None


def _methods(cls, options, base):
    methods = {}
    for attr, fn in _members(cls).items():
        if not inspect.isfunction(fn):
            continue  # classmethods, staticmethods, properties, data
        marker = fn.__dict__.get(METHOD_MARKER)
        listed = options["methods"].get(attr)
        if listed is False:
            continue
        automatic = (
            options["all_methods"]
            and not attr.startswith("_")
            and attr not in base
            and not any(m in fn.__dict__ for m in _CALLBACK_MARKERS)
        )
        if marker is None and listed is None and not automatic:
            continue
        if attr in base:
            msg = f"{cls.__name__}.{attr} is part of trame's API and cannot be exposed"
            raise ValueError(msg)
        check_progress(fn, f"{cls.__name__}.{attr}")
        opts = {**(marker or {}), **(listed or {})}
        public = opts.get("name") or attr
        if public in methods:
            msg = f"{cls.__name__}: two methods are exposed as {public!r}"
            raise ValueError(msg)
        annotations = dict(opts.get("annotations") or {})
        read_only = annotations.pop("readOnlyHint", False) or opts.get("read_only")
        methods[public] = Method(
            name=public,
            attr=attr,
            description=opts.get("description") or docstring(fn) or "",
            read_only=bool(read_only),
            annotations=annotations or None,
            concurrent=bool(opts.get("concurrent", False)),
            requires=tuple(opts.get("requires", ())),
        )
    return methods


def _constructor(cls):
    """``(Constructor or None, warning or None)``, from the class's
    ``_mcp_constructor`` hook."""
    declared = cls._mcp_constructor()
    if declared is None:
        return None, None
    if declared.problem:
        return None, declared.problem
    if declared.attr is None:
        constructor = Constructor(
            attr=None,
            description=declared.description,
            requires=tuple(declared.requires),
        )
        return constructor, None

    attr = declared.attr
    member = inspect.getattr_static(cls, attr, None)
    if not isinstance(member, classmethod):
        msg = f"{cls.__name__}.{attr} is the constructor but is not a classmethod"
        raise ValueError(msg)
    parameters = list(inspect.signature(getattr(cls, attr)).parameters)
    if not parameters:
        msg = (
            f"{cls.__name__}.{attr}: a constructor takes the trame server as its "
            f"first parameter after cls"
        )
        raise ValueError(msg)
    return (
        Constructor(
            attr=attr,
            description=declared.description or docstring(member.__func__) or "",
            requires=tuple(declared.requires),
            server=parameters[0],
        ),
        None,
    )


def subclasses(cls):
    """``cls`` and all its subclasses."""
    result, stack = [], [cls]
    while stack:
        klass = stack.pop()
        result.append(klass)
        stack.extend(klass.__subclasses__())
    return result
