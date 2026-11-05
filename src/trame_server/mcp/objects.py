"""The objects agents reach, and the six tools that work on them.

Objects are:

- instances of ``MCPExposable`` classes, such as components
  (``TrameComponent``) and trame-dataclass models, whose class declares
  something. Agents reach them by the names the application
  gives them, or by id through the visible properties of an object they
  already reach;
- the ``state`` object, whose properties are the state keys the
  application exposes (``state.mcp_expose()``).

``object_list``, ``object_types``, ``object_get``, ``object_update``,
``object_call`` and ``object_batch`` serve all objects, so the tool list
never changes as objects come and go.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import weakref
from dataclasses import dataclass, field
from typing import Annotated, Literal

from trame_server.mcp import budget, progress, typeinfo
from trame_server.mcp.permissions import PermissionDeniedError
from trame_server.mcp.schema import (
    ToolError,
    ValidationError,
    bind_arguments,
    error_text,
    from_json,
    function_input_schema,
    is_object,
    object_classes,
    resolve_object_arguments,
    return_hint,
    type_to_schema,
    validate,
)
from trame_server.mcp.typeinfo import (
    STATE_TYPE,
    Property,
    TypeInfo,
    is_visible,
    property_schema,
    reference_schema,
    subclasses,
    type_info,
    type_name,
)

logger = logging.getLogger("trame_server.mcp")

__all__ = ["OBJECT_TOOLS", "BatchError", "NotFoundError", "ObjectLayer", "StateObject"]

OBJECT_TOOLS = (
    "object_list",
    "object_types",
    "object_get",
    "object_update",
    "object_call",
    "object_batch",
)
STATE_NAME = "state"
NAME = re.compile(r"^[A-Za-z_]")
MAX_DEPTH = 10
# Objects the connection instructions name
MAX_LISTED = 20
# The object tools' parameters, as their input schemas say
Target = Annotated[str, "Object name or id"]
Depth = Annotated[int, {"minimum": 1, "maximum": MAX_DEPTH}]
Offset = Annotated[int, {"minimum": 0}]
TypeNames = Annotated[
    list[str] | None,
    'Types ("Viewer") or members ("Viewer.reset")',
]

LIST_DESCRIPTION = """\
List the objects this app names, as {"objects": {name: {"type", "read_only"?, \
"description"?}}}. "description" says what the object is for; "type" is null \
while the name holds nothing. The objects they refer to are reached by id, as \
object_get shows them. When "more" is present, it gives the call that lists \
the next ones."""

TYPES_DESCRIPTION = """\
Describe the types of this app's objects. Without `type_names`, it returns an \
index of the types; with them, types in full ("Viewer") or single members \
("Viewer.set_view_up"). A subclass lists what it adds, under "extends", unless \
`include_inherited`; false marks what it lacks. \
{"object": "T"} is a value holding an object of type T: read as a reference, \
returned by a method as object_get shows it, written by its id."""

GET_DESCRIPTION = """\
Read an object. `target` is an object name or id. \
The reply is {"result", "objects"}: "result" refers to what was read, and \
"objects" holds each object read, by id, once, as {"type", "values"}. A \
reference is {"id"}, and {"id", "type"} for an object not read here. `depth` \
reads objects up to that many references away. `properties` reads only those, \
in full. What is cut short is listed under "more", with the call that reads \
the rest."""

UPDATE_DESCRIPTION = """\
Write properties of an object: `values` maps property names to values \
(objects by id), as object_get reads them. Every value is checked before any \
is applied."""

CALL_DESCRIPTION = """\
Call a method of an object. `args` maps parameter names to values (objects by \
id or name). A result holding objects comes back as object_get shows it."""

BATCH_DESCRIPTION = """\
Run steps in order, in one call: {"new": "<Type>", "args", "as"} builds an \
object; {"call": target, "method", "args", "as"}; {"update": target, "values"}. \
"@name" is the result of the step named so ("@name.prop.0" follows properties \
and indexes, "@@" is a literal "@"). Steps are checked before any runs; the \
first failure stops the batch and earlier steps stay applied. An object built \
and never attached is dropped, listed in "unattached". Objects are read as \
object_get does; with `results` "links", only their references to others."""

_STEP_KEYS = {
    "new": ("new", "args", "as"),
    "call": ("call", "method", "args", "as"),
    "update": ("update", "values"),
}
_STEP_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_HIDDEN = object()


async def _settle(obj):
    """Wait for the work a change started, such as the watchers trame-dataclass runs
    in a task. Without this, the reply and the agent's next read would not reflect
    what that work derives."""
    if not is_object(obj):
        return
    try:
        await obj._mcp_settle()
    except Exception:
        # The change itself is applied: a failing watcher is the app's bug,
        # not the agent's, and must not read as "nothing was applied".
        logger.exception("A watcher of %s %s raised", type(obj).__name__, obj._id)


# -----------------------------------------------------------------------------
# The state object
# -----------------------------------------------------------------------------


class StateObject:
    """The ``state`` object: its properties are the trame state keys the app
    exposed (``server.state.mcp_expose()``), with their real names (a child
    server's prefix included)."""

    _id = STATE_NAME

    def __init__(self):
        self._keys = {}  # key -> Property
        self._info = None

    def __bool__(self):
        return bool(self._keys)

    def expose(self, key, *, type=None, schema=None, description=None, read_only=False):
        if not isinstance(read_only, bool):
            msg = "read_only must be True or False"
            raise TypeError(msg)
        var_schema, description = property_schema(
            type, {"schema": schema, "description": description}
        )
        self._keys[key] = Property(
            name=key,
            origin="state",
            schema=var_schema,
            description=description,
            writable=not read_only,
            type_def=type,
        )
        self._info = None

    def unexpose(self, *keys):
        for key in keys:
            self._keys.pop(key, None)
        self._info = None

    @property
    def info(self) -> TypeInfo:
        if self._info is None:
            self._info = TypeInfo(cls=None, visible=True, properties=dict(self._keys))
        return self._info


# -----------------------------------------------------------------------------
# Exposure
# -----------------------------------------------------------------------------


class _Entry:
    """What a name exposes: an object, or a getter that returns one or None and is
    called again on every request. The object is held weakly when its class asks
    for it, as components do."""

    __slots__ = ("_value", "description", "read_only", "source_type")

    def __init__(self, source_type, value, description, read_only):
        self.source_type = source_type
        self.description = description
        self.read_only = bool(read_only)
        if source_type == "weak":
            try:
                value = weakref.ref(value)
            except TypeError:  # no __weakref__: held
                source_type = self.source_type = "object"
        self._value = value

    def resolve(self):
        if self.source_type in ("weak", "getter"):
            return self._value()
        return self._value

    def holds(self, obj):
        """Whether this entry names ``obj`` itself."""
        return self.source_type in ("weak", "object") and self.resolve() is obj

    def exposes(self, source):
        """Whether ``source`` is what this entry was given."""
        if self.source_type == "getter":
            return self._value == source  # bound methods are rebuilt on access
        return self.resolve() is source

    def gone(self):
        """Whether the object this entry held weakly was garbage collected."""
        return self.source_type == "weak" and self._value() is None


@dataclass
class Graph:
    """What agents reach now.

    ``objects`` maps ids to ``(object, writable)``; ``entries`` maps names
    to ``(value, read_only)``; ``names`` maps ids to the names exposing them.
    """

    objects: dict
    entries: dict
    names: dict = field(default_factory=dict)


@dataclass
class _Read:
    """An object read for a reply, with its raw property values."""

    obj: object
    writable: bool
    distance: int  # references away from what was read
    raw: dict
    errors: dict


class _Scope:
    """What one ``object_batch`` holds: the results named with ``as``, and
    the models its ``new`` steps built (held until it ends)."""

    def __init__(self):
        self.names = {}
        self.built = {}  # _id -> model


class NotFoundError(ToolError, LookupError):
    """An object, type, member or property the agent named does not exist. The
    message lists what does exist."""


class BatchError(ToolError):
    """An ``object_batch`` step failed. The message says which one, why, and what the
    steps before it returned."""


class ObjectLayer:
    """The objects of one MCP server and the object tools."""

    def __init__(self, mcp):
        self._mcp = mcp
        self._entries = {}  # name -> _Entry
        self.state = StateObject()
        self._registered = False
        self._warned = weakref.WeakSet()  # classes warned about

    # -------------------------------------------------------------------------
    # Exposure (server.mcp)
    # -------------------------------------------------------------------------

    def remove(self, obj):
        """Withdraw every name exposing ``obj``."""
        for name in [n for n, e in self._entries.items() if e.holds(obj)]:
            del self._entries[name]

    def expose(self, source, name, description=None, read_only=False):
        if not isinstance(name, str) or not NAME.match(name):
            msg = f"An object name starts with a letter or an underscore, got {name!r}"
            raise ValueError(msg)
        if name == STATE_NAME:
            msg = (
                f"{STATE_NAME!r} is reserved for the state object "
                f"(server.state.mcp_expose())"
            )
            raise ValueError(msg)
        if description is not None and not isinstance(description, str):
            msg = f"description must be a string, got {type(description).__name__}"
            raise TypeError(msg)

        if is_object(source):
            if not is_visible(type(source)):
                cls = type(source).__name__
                msg = (
                    f"{cls} declares nothing for agents: mark its members with "
                    f"@mcp.method / @mcp.property, or use the mcp= class keyword "
                    f"(or {cls}.mcp_describe() for a class you don't own)"
                )
                raise TypeError(msg)
            source_type = "weak" if type(source)._mcp_hold_weakly else "object"
        elif callable(source) and not isinstance(source, type):
            source_type = "getter"
        else:
            msg = (
                "expose_object() takes a component, a model, or a function "
                f"returning one; got {type(source).__name__}. Expose the items "
                f"of a list each under its own name, or through a property of "
                f"an object."
            )
            raise TypeError(msg)

        current = self._entries.get(name)
        if current is not None and not current.gone() and not current.exposes(source):
            if current.source_type == "getter":
                held = "a function"
            else:
                held = self._label(current.resolve())
            msg = (
                f"{name!r} already exposes {held}; withdraw it first "
                f"(server.mcp.unexpose_object({name!r}))"
            )
            raise ValueError(msg)
        self._entries[name] = _Entry(source_type, source, description, read_only)
        self._ensure_tools()

    def unexpose(self, name):
        if self._entries.pop(name, None) is None:
            msg = f"No object is exposed as {name!r}"
            raise KeyError(msg)

    def expose_state(self, key, **options):
        self.state.expose(key, **options)
        self._ensure_tools()

    def exposes_anything(self):
        return bool(self._entries or self.state)

    # -------------------------------------------------------------------------
    # Reachability
    # -------------------------------------------------------------------------

    def _is_object(self, value):
        return is_object(value) and is_visible(type(value))

    def _info(self, obj) -> TypeInfo:
        if obj is self.state:
            return self.state.info
        return type_info(type(obj))

    def _type(self, obj) -> str:
        if obj is self.state:
            return STATE_TYPE
        return type_name(type(obj))

    def _label(self, obj) -> str:
        if obj is self.state:
            return STATE_NAME
        return f"{self._type(obj)} {obj._id}"

    def _read(self, obj, prop):
        if prop.origin == "state":
            return self._mcp.server.state[prop.name]
        return getattr(obj, prop.name)

    def _readable(self, info):
        """``{name: Property}`` of the properties agents may read now: those
        whose permissions are on."""
        permissions = self._mcp.permissions
        return {
            name: prop
            for name, prop in info.properties.items()
            if permissions.allows(prop.requires)
        }

    def _children(self, obj):
        for prop in self._readable(self._info(obj)).values():
            if not prop.reference:
                continue
            try:
                value = self._read(obj, prop)
            except Exception:
                logger.debug("Reading %s.%s raised", self._type(obj), prop.name)
                continue
            yield from _objects_within(value, self._is_object)

    def _graph(self, scope=None) -> Graph:
        """Everything agents reach now: what names expose, and the objects
        visible properties refer to from there. An object is writable when a
        writable path reaches it."""
        entries = {}
        for name, entry in list(self._entries.items()):
            try:
                value = entry.resolve()
            except Exception:
                logger.exception("Resolving the object exposed as %r raised", name)
                value = None
            if value is not None and not self._is_object(value):
                logger.warning(
                    "%r exposes a %s, not a component or model agents can see",
                    name,
                    type(value).__name__,
                )
                value = None
            entries[name] = (value, entry.read_only)

        names = {}  # id -> the names exposing it
        roots = []
        for name, (value, read_only) in entries.items():
            if value is not None:
                names.setdefault(value._id, []).append(name)
                roots.append((value, not read_only))
        if scope is not None:
            roots.extend((obj, True) for obj in scope.built.values())

        objects = {}
        for writable in (True, False):
            stack = [obj for obj, w in roots if w is writable]
            while stack:
                obj = stack.pop()
                if obj._id in objects:
                    continue
                objects[obj._id] = (obj, writable)
                stack.extend(self._children(obj))
        if self.state:
            objects[STATE_NAME] = (self.state, True)

        return Graph(objects=objects, entries=entries, names=names)

    def _unknown(self, target, graph):
        names = [*graph.entries, *([STATE_NAME] if self.state else [])]
        if not names:
            return (
                f"Unknown object {json.dumps(target)}: no object has that name or "
                f"id; object_list() lists the objects."
            )
        return (
            f"Unknown object {json.dumps(target)}. Objects: {', '.join(names)} "
            f"(or an object id); object_list() lists them all."
        )

    def _object(self, target, graph):
        """``(object, writable)`` for a target name or id."""
        if not isinstance(target, str) or not target:
            msg = "`target` must be an object name or id"
            raise ValidationError(msg)
        if target in graph.entries:
            value, _ = graph.entries[target]
            if value is None:
                msg = f"The object exposed as {json.dumps(target)} is currently empty"
                raise NotFoundError(msg)
            found = graph.objects.get(value._id)
            if found is not None:
                return found
        found = graph.objects.get(target)
        if found is not None:
            return found
        raise NotFoundError(self._unknown(target, graph))

    def _resolver(self, scope, read_only):
        """``resolve(value, cls, path)`` for object-typed parameters and
        properties: an id or name of a reachable object of class ``cls``."""
        graph = None

        def resolve(value, cls, path):
            nonlocal graph
            if graph is None:
                graph = self._graph(scope)
            found = graph.objects.get(value)
            if found is None and value in graph.entries:
                named = graph.entries[value][0]
                if named is not None:
                    found = graph.objects.get(named._id)
            expected = type_name(cls)
            if found is None or found[0] is self.state:
                msg = (
                    f"{path}: {json.dumps(value)} is not the id or name of an object "
                    f"agents can reach (an object of type {expected} is expected)"
                )
                raise ValidationError(msg)
            obj, writable = found
            if not isinstance(obj, cls):
                msg = (
                    f"{path}: {json.dumps(value)} has type {self._type(obj)}, "
                    f"not {expected}"
                )
                raise ValidationError(msg)
            if not writable and not read_only:
                msg = (
                    f"{path}: {self._label(obj)} is exposed read-only; only read-only "
                    f"methods can take it"
                )
                raise PermissionError(msg)
            return obj

        return resolve

    def resolve_arguments(
        self, fn, arguments, *, read_only=False, scope=None, label="arguments"
    ):
        """``arguments`` of ``fn``, with the ids or names given for its object-typed
        parameters replaced by the objects. An object must be reachable (or built
        by the batch ``scope``) and of the annotated class, and one reached only
        read-only can be passed to ``read_only`` callables only."""
        return resolve_object_arguments(
            fn, arguments, self._resolver(scope, read_only), label
        )

    # -------------------------------------------------------------------------
    # Replies: what was read, with its objects as references, and the
    # objects read, once each, in a flat table
    # -------------------------------------------------------------------------

    def _reply(
        self,
        value,
        graph,
        depth=1,
        *,
        target=None,
        writable=True,
        properties=None,
        links=False,
        spread=False,
    ):
        """``{"result", "objects"?, "more"?}``: ``value`` with its objects as
        references, and the objects within ``depth`` steps of it read into
        ``objects``, by id, nearest first. A reference is ``{"id"}`` for an object
        that is read, and ``{"id", "type"}`` for one that is not.

        Over the budget, the farthest objects are left out first, since
        object_get reads them again; ``value`` is cut last.

        :param target: the name the agent used for ``value``, used in the calls
            that notes suggest.
        :param writable: whether ``value``, a target object, is writable.
        :param properties: the only properties of ``value`` to read, which
            come back whole.
        :param links: read only the properties holding objects.
        :param spread: ``value``, a dict, gives the reply's own fields in
            place of ``result``.
        """
        reads = self._gather(value, graph, depth, writable, properties)
        order = list(reads)
        requested = set(properties or ())

        def call_target(obj_id):
            return target if target and reads[obj_id].obj is value else obj_id

        def build(count):
            read = set(order[:count])
            more = {}
            objects = {}
            for obj_id in order[:count]:
                entry, notes = self._entry(
                    reads[obj_id],
                    graph,
                    reads,
                    read,
                    (call_target(obj_id), depth),
                    links,
                    requested,
                )
                objects[obj_id] = entry
                more.update(notes)
            if count < len(order):
                more["objects"] = (
                    f"{count} of {len(order)} objects read to fit the response "
                    f"budget; object_get(id) reads one"
                )
            result = self._encode(value, graph, reads, read)
            reply = {"result": None if result is _HIDDEN else result}
            if objects:
                reply["objects"] = objects
            if more:
                reply["more"] = more
            return reply

        def finish(reply):
            if spread:
                return {**reply.pop("result"), **reply}
            return reply

        room = self._budget()
        reply = build(len(order))
        if budget.size(reply) <= room:
            return finish(reply)
        # Leave out the farthest objects: the most that fit. One object read
        # for itself stays, and its values are cut instead.
        single = bool(order) and reads[order[0]].obj is value
        low, high = int(single), len(order) - 1
        while low < high:
            middle = (low + high + 1) // 2
            if budget.size(build(middle)) <= room:
                low = middle
            else:
                high = middle - 1
        reply = build(low)
        if budget.size(reply) <= room:
            return finish(reply)
        if single:  # the object read alone is still too big
            return self._fit_entry(
                reply, reads[order[0]], requested, (call_target(order[0]), depth)
            )
        # Then the result, noted under the fields the agent sees
        result = reply["result"] if spread else {"result": reply["result"]}
        rest = budget.size({k: v for k, v in reply.items() if k != "result"})
        result, cuts = budget.shrink(result, room - rest - 200)
        reply["result"] = result if spread else result["result"]
        more = reply.setdefault("more", {})
        for key, note in cuts.items():
            more[key] = f"{note} to fit the response budget"
        return finish(reply)

    def _gather(self, value, graph, depth, writable, properties):
        """``{id: _Read}``: the objects ``value`` holds, when agents can see their type,
        then those reachable within ``depth`` steps, nearest first."""
        reads = {}
        pending = []

        def admit(obj, distance):
            if obj._id in reads or distance >= depth:
                return
            found = graph.objects.get(obj._id)
            if distance == 0:  # what was read: the target, or a call's result
                if obj is not self.state and not is_visible(type(obj)):
                    return
                if obj is value:
                    obj_writable = writable
                else:
                    obj_writable = found[1] if found and found[0] is obj else True
            elif found is None or found[0] is not obj:
                return
            else:
                obj_writable = found[1]
            wanted = properties if obj is value else None
            reads[obj._id] = self._read_object(obj, obj_writable, distance, wanted)
            pending.append(obj._id)

        def visit(raw, distance, capped):
            # A capped value keeps only its first items (see _entry). The
            # objects in the other items are not shown, so they are not read
            limit = budget.MAX_ITEMS if capped else None
            for obj in _objects_within(raw, obj_like, limit):
                admit(obj, distance)

        def obj_like(raw):
            return raw is self.state or is_object(raw)

        visit(value, 0, False)
        requested = set(properties or ())
        index = 0
        while index < len(pending):
            read = reads[pending[index]]
            index += 1
            for name, raw in read.raw.items():
                whole = read.distance == 0 and name in requested
                visit(raw, read.distance + 1, not whole)
        return reads

    def _read_object(self, obj, writable, distance, wanted=None):
        raw, errors = {}, {}
        for prop in self._readable(self._info(obj)).values():
            if wanted is not None and prop.name not in wanted:
                continue
            try:
                raw[prop.name] = self._read(obj, prop)
            except Exception as e:
                errors[prop.name] = error_text(e)
        return _Read(obj, writable, distance, raw, errors)

    def _encode(self, value, graph, reads, read):
        """``value`` as JSON: objects as references, those agents cannot
        reach left out (``_HIDDEN``)."""
        if value is self.state or is_object(value):
            if value._id in read:
                return {"id": value._id}
            found = graph.objects.get(value._id)
            known = reads.get(value._id)
            if (known is not None and known.obj is value) or (
                found is not None and found[0] is value
            ):
                return {"id": value._id, "type": self._type(value)}
            return _HIDDEN
        if isinstance(value, (list, tuple, set, frozenset)):
            items = [self._encode(v, graph, reads, read) for v in value]
            items = [v for v in items if v is not _HIDDEN]
            if isinstance(value, (set, frozenset)):
                return sorted(items, key=str)
            return items
        if isinstance(value, dict):
            items = {
                str(k): self._encode(v, graph, reads, read) for k, v in value.items()
            }
            return {k: v for k, v in items.items() if v is not _HIDDEN}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        tolist = getattr(value, "tolist", None)  # numpy and friends
        if callable(tolist):
            try:
                return self._encode(tolist(), graph, reads, read)
            except Exception:
                pass
        return str(value)

    def _entry(self, found, graph, reads, read, call, links, requested):
        """``(entry, more)``: an object read, as ``objects`` lists it, with its
        values capped unless they were requested. ``call`` is ``(target,
        depth)``, used in the calls that notes suggest."""
        obj = found.obj
        target, depth = call
        values, more = {}, {}
        for name, raw in found.raw.items():
            rendered = self._encode(raw, graph, reads, read)
            rendered = None if rendered is _HIDDEN else rendered
            if links and not _holds_references(rendered):
                continue
            if found.distance or name not in requested:
                rendered, note = budget.cap(rendered)
                if note:
                    rest = self._get_call(target, name, depth - found.distance)
                    more[f"{obj._id}.{name}"] = f"{note}; {rest} for all"
            values[name] = rendered
        entry = {"type": self._type(obj)}
        if graph.names.get(obj._id):
            entry["names"] = graph.names[obj._id]
        if values:
            entry["values"] = values
        if found.errors:
            entry["errors"] = found.errors
        if not found.writable:
            entry["read_only"] = True
        return entry, more

    def encode_tool_result(self, value):
        """An app tool's result, the way object_get shows it when it holds objects, and
        as is otherwise."""
        if not _holds_objects(value):
            return value
        return self._reply(value, self._graph())

    def _encode_result(self, value, graph):
        """A method's or constructor's result, the way object_get shows it when it holds
        objects. Anything else is returned as is, cut to fit the budget."""
        if _holds_objects(value):
            reply = self._reply(value, graph)
            if reply["result"] is None and not reply.get("objects"):
                return None
            return reply
        return self._fit_result(value)

    # -------------------------------------------------------------------------
    # Response budget
    # -------------------------------------------------------------------------

    def _budget(self):
        return self._mcp.max_response_tokens * budget.CHARS_PER_TOKEN

    @staticmethod
    def _get_call(target, name, depth=1):
        call = f"object_get({json.dumps(target)}, properties=[{json.dumps(name)}]"
        if depth > 1:
            call += f", depth={depth}"
        return f"{call})"

    def _fit_entry(self, reply, found, requested, call):
        """Cut the largest values of a reply that reads one object, until it fits. Notes
        go in ``reply["more"]``, keyed ``id.property``, and their counts come from the
        values ``found`` read, before they were capped."""
        target, depth = call
        obj_id = found.obj._id
        entry = reply["objects"][obj_id]
        values, more = entry.get("values", {}), reply.setdefault("more", {})
        room = self._budget() - budget.size({**reply, "objects": {}})
        room -= budget.size({obj_id: {**entry, "values": {}}})
        if budget.size(values) > room:
            totals = {
                name: len(raw)
                for name, raw in found.raw.items()
                if isinstance(raw, (str, list, tuple, set, frozenset))
            }
            values, cuts = budget.shrink(values, room, totals)
            for name, note in cuts.items():
                if name in requested:
                    more[f"{obj_id}.{name}"] = f"{note} to fit the response budget"
                else:
                    rest = self._get_call(target, name, depth)
                    more[f"{obj_id}.{name}"] = f"{note}; {rest} alone for more"
            while values and budget.size(values) > room - budget.size(more):
                name = max(values, key=lambda k: budget.size(values[k]))
                del values[name]
                rest = self._get_call(target, name, depth)
                more[f"{obj_id}.{name}"] = (
                    f"left out to fit the response budget; {rest}"
                )
            if values:
                entry["values"] = values
            else:
                entry.pop("values", None)
        return reply

    def _fit_result(self, value):
        """A plain value (a method's result) cut to fit the budget."""
        room = self._budget()
        if budget.size(value) <= room:
            return value
        wrapped, cuts = budget.shrink({"result": value}, room - 120)
        note = cuts.get("result", "shortened")
        return {
            "result": wrapped["result"],
            "more": f"{note} to fit the response budget",
        }

    # -------------------------------------------------------------------------
    # object_list and object_types
    # -------------------------------------------------------------------------

    def _catalog(self, graph):
        """``{type name: TypeInfo}``: the types of the objects, those their
        properties may hold (with visible subclasses), and the visible bases
        they extend."""
        pending = [
            type(obj) for obj, _ in graph.objects.values() if obj is not self.state
        ]
        known, expanded = set(), set()
        while pending:
            cls = pending.pop()
            if cls in known or not is_visible(cls):
                continue
            known.add(cls)
            for prop in type_info(cls).properties.values():
                if prop.reference:
                    for held in object_classes(prop.type_def):
                        if held not in expanded:
                            expanded.add(held)
                            pending.extend(subclasses(held))
        for cls in list(known):
            base = self._base(cls)
            while base is not None and base not in known:
                known.add(base)
                base = self._base(base)
        catalog = {type_name(cls): type_info(cls) for cls in known}
        if self.state:
            catalog[STATE_TYPE] = self.state.info
        return dict(sorted(catalog.items()))

    @staticmethod
    def _base(klass):
        """The nearest visible base of ``klass``, which it can extend."""
        for base in klass.__mro__[1:]:
            if is_visible(base):
                return base
        return None

    def _render(self, info) -> dict:
        """A type in full: what agents may use of it now."""
        permissions = self._mcp.permissions
        entry = {}
        if info.description:
            entry["description"] = info.description
        properties = {}
        for prop in self._readable(info).values():
            item = prop.described()
            writable = prop.writable and permissions.allows(prop.set_requires)
            if not writable:
                item["read_only"] = True
            requires = prop.requires + (prop.set_requires if writable else ())
            if requires:
                item["requires"] = list(dict.fromkeys(requires))
            properties[prop.name] = item
        methods = {}
        for method in info.methods.values():
            if not permissions.allows(method.requires):
                continue
            fn = getattr(info.cls, method.attr)
            item = {"parameters": function_input_schema(fn, ref=reference_schema)}
            if method.description:
                item = {"description": method.description, **item}
            returns = type_to_schema(return_hint(fn), reference_schema)
            if returns and returns != {"type": "null"}:
                item["returns"] = returns
            if method.read_only:
                item["read_only"] = True
            if method.annotations:
                item["annotations"] = dict(method.annotations)
            if method.requires:
                item["requires"] = list(method.requires)
            methods[method.name] = item
        entry["properties"] = properties
        entry["methods"] = methods
        constructor = info.constructor
        if constructor is not None and permissions.allows(constructor.requires):
            item = {"parameters": self._constructor_schema(info)}
            if constructor.description:
                item["description"] = constructor.description
            if constructor.requires:
                item["requires"] = list(constructor.requires)
            entry["constructor"] = item
        if info.constructor_warning and info.cls not in self._warned:
            self._warned.add(info.cls)
            logger.warning(
                "%s has no constructor for agents: %s",
                info.cls.__name__,
                info.constructor_warning,
            )
        return entry

    def _rendered(self, catalog, include_inherited):
        """``{name: entry}``: each type in full, or as what it adds to the
        type it extends."""
        full = {name: self._render(info) for name, info in catalog.items()}
        result = {}
        for name, info in catalog.items():
            entry = full[name]
            base = (
                None if include_inherited or info.cls is None else self._base(info.cls)
            )
            if base is not None:
                base_name = type_name(base)
                if base_name not in full:
                    full[base_name] = self._render(type_info(base))
                entry = _extending(entry, base_name, full[base_name])
            result[name] = entry
        return result

    def _named(self, graph, short=False):
        """``{name: {"type", "read_only"?, "description"?}}`` for the names agents
        start from, in the order they were given. ``type`` is None while a name
        holds nothing, and with ``short`` the description is only its first
        sentence."""
        named = {}
        for name, (value, read_only) in graph.entries.items():
            item = {"type": None if value is None else self._type(value)}
            if read_only:
                item["read_only"] = True
            about = self._entries[name].description
            if about and short:
                about = _first_sentence(about)
            if about:
                item["description"] = about
            named[name] = item
        if self.state:
            named[STATE_NAME] = {"type": STATE_TYPE}
        return named

    def list_objects(self, offset: Offset = 0):
        items = list(self._named(self._graph()).items())
        start = offset
        # As many as fit, one at least, with room for the note
        room = self._budget() - 200
        used, end = budget.size({"objects": {}}), start
        while end < len(items):
            name, item = items[end]
            used += budget.size({name: item})
            if used > room and end > start:
                break
            end += 1
        result = {"objects": dict(items[start:end])}
        if end < len(items):
            result["more"] = {
                "objects": (
                    f"{start + 1}-{end} of {len(items)} listed to fit the response "
                    f"budget; object_list(offset={end}) lists the next ones"
                )
            }
        return result

    def types(self, type_names: TypeNames = None, include_inherited: bool = False):
        graph = self._graph()
        catalog = self._catalog(graph)
        if type_names is None:
            rendered = self._rendered(catalog, include_inherited)
            index = {name: _index_entry(e) for name, e in rendered.items()}
            return self._fit_index({"types": index})

        known = {**typeinfo.type_names()[1], **dict.fromkeys(catalog)}
        wanted, members, unknown = [], [], []
        for raw in dict.fromkeys(type_names):
            if raw in known:
                wanted.append(raw)
            else:
                owner, _, member = raw.rpartition(".")
                if owner in known and member:
                    members.append((owner, member))
                else:
                    unknown.append(raw)

        def info_of(name):
            return catalog.get(name) or type_info(typeinfo.type_names()[1][name])

        found, missing = [], []
        for owner, member in members:
            entry = self._render(info_of(owner))
            section = next(
                (k for k in ("properties", "methods") if member in entry[k]), None
            )
            if section is not None:
                found.append((owner, section, member, entry[section][member]))
            elif member == "constructor" and "constructor" in entry:
                found.append((owner, None, member, entry["constructor"]))
            else:
                missing.append(f"{owner}.{member}")
        # Every name that is wrong, in one reply
        problems = []
        if unknown:
            problems.append(
                f"Unknown types or members: {', '.join(unknown)}. Types: "
                f"{', '.join(catalog)}; object_types() lists them."
            )
        if missing:
            problems.append(
                f"No member {', '.join(missing)}; object_types([type]) lists a "
                f"type's properties and methods."
            )
        if problems:
            raise NotFoundError(" ".join(problems))

        selected = {name: info_of(name) for name in dict.fromkeys(wanted)}
        rendered = self._rendered(selected, include_inherited) if selected else {}
        for owner, section, member, value in found:
            if section is None:
                rendered.setdefault(owner, {})[member] = value
            else:
                rendered.setdefault(owner, {}).setdefault(section, {})[member] = value
        result = {"types": rendered}
        if budget.size(result) > self._budget():
            types, cuts = budget.shrink(rendered, self._budget() - 200)
            result = {"types": types}
            if cuts:
                result["more"] = dict.fromkeys(
                    cuts,
                    "shortened to fit the response budget; describe fewer types per call",
                )
        return result

    def _fit_index(self, result):
        room = self._budget()
        if budget.size(result) <= room:
            return result
        for entry in result["types"].values():
            entry.pop("properties", None)
            entry.pop("methods", None)
        note = (
            'member names left out to fit the response budget; object_types(["Type"]) '
            "for a type's members"
        )
        if budget.size(result) > room:
            types = list(result["types"].items())
            keep = len(types)
            while keep > 1 and budget.size(dict(types[:keep])) > room - 200:
                keep //= 2
            result["types"] = dict(types[:keep])
            note = (
                f"{keep} of {len(types)} types shown, member names left out, to fit "
                f'the response budget; object_types(["Type"]) for one type'
            )
        result["more"] = {"types": note}
        return result

    def describe_class(self, cls):
        """What agents see of ``cls`` now (``server.mcp.describe(cls)``)."""
        if cls is None or cls == STATE_TYPE:
            return self._render(self.state.info)
        info = type_info(cls)
        if not info.visible:
            return None
        return self._render(info)

    # -------------------------------------------------------------------------
    # object_get
    # -------------------------------------------------------------------------

    def get(
        self, target: Target, properties: list[str] | None = None, depth: Depth = 1
    ):
        graph = self._graph()
        value, writable = self._object(target, graph)
        if properties is not None:
            visible = list(self._readable(self._info(value)))
            unknown = [p for p in properties if p not in visible]
            if unknown:
                msg = (
                    f"{self._label(value)} has no properties {unknown}; its properties: "
                    f"{', '.join(visible)}"
                )
                raise NotFoundError(msg)
        return self._reply(
            value,
            graph,
            depth,
            target=target,
            writable=writable,
            properties=properties,
        )

    # -------------------------------------------------------------------------
    # object_update
    # -------------------------------------------------------------------------

    async def update(self, target: Target, values: dict):
        obj, writable = self._object(target, self._graph())
        return await self._apply_update(obj, writable, values)

    async def _apply_update(self, obj, writable, values, scope=None):
        label = self._label(obj)
        if not writable:
            msg = f"Nothing was applied: {label} is exposed read-only."
            raise PermissionError(msg)

        info, permissions = self._info(obj), self._mcp.permissions
        props = self._readable(info)
        rejected, read_only = [], False
        for name in values:
            prop = props.get(name)
            if prop is None:
                rejected.append(f"{name} (unknown)")
            elif not prop.writable:
                rejected.append(f"{name} (read-only)")
                read_only = True
            elif not permissions.allows(prop.set_requires):
                off = [n for n in prop.set_requires if not permissions.allows((n,))]
                rejected.append(
                    f"{name} (read-only: permission {', '.join(off)} is off)"
                )
                read_only = True
        if rejected:
            writable_names = [
                n
                for n, p in props.items()
                if p.writable and permissions.allows(p.set_requires)
            ]
            msg = (
                f"Nothing was applied. Rejected on {label}: {', '.join(rejected)}. "
                f"Writable: {', '.join(writable_names) or 'none'}"
            )
            # Methods may change what can't be written: point at them
            methods = [
                m.name for m in info.methods.values() if permissions.allows(m.requires)
            ]
            if read_only and methods:
                msg += (
                    f". Methods: {', '.join(methods)}; "
                    f"object_types([{json.dumps(self._type(obj))}]) says what "
                    f"they do."
                )
            raise ValidationError(msg)

        converted, errors = {}, []
        resolve = self._resolver(scope, read_only=False)
        for name, value in values.items():
            prop = props[name]
            try:
                converted[name] = from_json(
                    validate(value, prop.schema, name),
                    prop.type_def,
                    resolve if prop.reference else None,
                    name,
                )
            except (ValidationError, PermissionError) as e:
                errors.append(str(e))
        if errors:
            msg = f"Nothing was applied: {'; '.join(errors)}"
            raise ValidationError(msg)

        state = self._mcp.server.state
        applied = []
        with state:
            # Fields and state keys first, all at once: they cannot fail
            for name, value in converted.items():
                if props[name].origin == "state":
                    state[name] = value
                    applied.append(name)
                elif props[name].origin == "field":
                    setattr(obj, name, value)
                    applied.append(name)
            # Then setters, in order: one that raises stops the update
            for name, value in converted.items():
                if props[name].origin != "property":
                    continue
                try:
                    setattr(obj, name, value)
                except Exception as e:
                    done = f"; applied: {', '.join(applied)}" if applied else ""
                    msg = f"Setting {label}.{name} failed: {error_text(e)}{done}"
                    raise ToolError(msg) from e
                applied.append(name)
        await _settle(obj)
        return {"id": obj._id, "updated": list(converted)}

    # -------------------------------------------------------------------------
    # object_call
    # -------------------------------------------------------------------------

    def _method(self, obj, writable, method, target):
        info = self._info(obj)
        permissions = self._mcp.permissions
        found = info.methods.get(method)
        if found is None:
            type_name = self._type(obj)
            msg = (
                f"{target} (type {type_name}) has no method {json.dumps(method)}; "
                f'object_types(["{type_name}"]) lists its methods.'
            )
            raise NotFoundError(msg)
        if not writable and not found.read_only:
            allowed = [n for n, m in info.methods.items() if m.read_only]
            msg = (
                f"{self._label(obj)} is exposed read-only; only read-only methods can "
                f"be called: {', '.join(allowed) or 'none'}"
            )
            raise PermissionError(msg)
        permissions.require(*found.requires, what=f"{self._type(obj)}.{found.name}")
        return found

    async def call(self, target: Target, method: str, args: dict | None = None):
        # object_call skips the protocol's lock: the method's own concurrent
        # option decides, so it is looked up first, then again under the
        # lock, where the objects are as earlier calls left them.
        obj, writable = self._object(target, self._graph())
        found = self._method(obj, writable, method, target)
        async with self._mcp.protocol.locked(found.concurrent):
            obj, writable = self._object(target, self._graph())
            found = self._method(obj, writable, method, target)
            _, encoded = await self._invoke(obj, found, args, "args")
        return encoded

    async def _invoke(self, obj, method, args, label, scope=None):
        """Call an exposed method: bind, resolve object ids, run, settle, and
        encode what it returns."""
        fn = getattr(obj, method.attr)
        schema = function_input_schema(fn, ref=reference_schema)
        try:
            args = bind_arguments(fn, args, schema, label=label)
        except ValidationError as e:
            msg = f"Invalid arguments for {self._type(obj)}.{method.name}: {e}"
            raise ValidationError(msg) from None
        args = self.resolve_arguments(
            fn, args, read_only=method.read_only, scope=scope, label=label
        )
        result = fn(**progress.inject(fn, args))
        if inspect.isawaitable(result):
            result = await result
        await _settle(obj)
        return result, self._encode_result(result, self._graph(scope))

    # -------------------------------------------------------------------------
    # object_batch
    # -------------------------------------------------------------------------

    def _constructor_schema(self, info):
        constructor = info.constructor
        if constructor.attr is not None:
            fn = getattr(info.cls, constructor.attr)
            return function_input_schema(
                fn, skip=(constructor.server,), ref=reference_schema
            )
        properties = {
            prop.name: prop.described()
            for prop in self._readable(info).values()
            if prop.origin == "field" and prop.writable
        }
        return {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }

    def _constructible(self, graph):
        """Types with a constructor, by name."""
        return {
            name: info
            for name, info in self._catalog(graph).items()
            if info.constructor is not None
        }

    @staticmethod
    def _references(value):
        """Every "@..." reference string inside a step value."""
        if isinstance(value, str):
            if value.startswith("@") and not value.startswith("@@"):
                yield value
        elif isinstance(value, list):
            for item in value:
                yield from ObjectLayer._references(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from ObjectLayer._references(item)

    def _check_steps(self, steps):
        """Validate every step before any runs, and return the types that can
        be built."""

        def fail(message):
            msg = f"Nothing was applied: {message}"
            raise ValidationError(msg)

        graph = self._graph()
        constructible = None
        defined = set()
        built = {}  # "as" name of a new step -> its TypeInfo
        for index, step in enumerate(steps):
            path = f"steps[{index}]"
            step_types = [step_type for step_type in _STEP_KEYS if step_type in step]
            if len(step_types) != 1:
                fail(f"{path}: a step has exactly one of 'new', 'call' or 'update'")
            step_type = step_types[0]
            unexpected = sorted(set(step) - set(_STEP_KEYS[step_type]))
            if unexpected:
                fail(
                    f"{path}: unexpected {unexpected}; {step_type} steps take "
                    f"{list(_STEP_KEYS[step_type])}"
                )
            if not isinstance(step[step_type], str) or not step[step_type]:
                fail(f"{path}.{step_type}: expected a non-empty string")
            if step_type == "call" and (
                not isinstance(step.get("method"), str) or not step["method"]
            ):
                fail(f"{path}: a call step needs 'method'")
            if step_type == "update" and not isinstance(step.get("values"), dict):
                fail(
                    f"{path}: an update step needs 'values', an object of property values"
                )
            if step.get("args") is not None and not isinstance(step["args"], dict):
                fail(f"{path}.args: expected an object")
            if step_type == "new":
                if constructible is None:
                    constructible = self._constructible(graph)
                name = step["new"]
                if name not in constructible:
                    fail(
                        f"{path}: no type {json.dumps(name)} can be built; types with a "
                        f"constructor: {', '.join(constructible) or 'none'}"
                    )
                info = constructible[name]
                self._check_permissions(
                    info.constructor.requires, f"{path} (new {name})"
                )
                if "as" in step:
                    built[step["as"]] = info
                checked = [step.get("args")]
            else:
                checked = [step[step_type], step.get("args"), step.get("values")]
                info = self._info_before_run(step[step_type], built, graph)
                if info is not None and step_type == "call":
                    method = info.methods.get(step["method"])
                    if method is not None:
                        what = f"{path} (call {step['method']} on {step[step_type]})"
                        self._check_permissions(method.requires, what)
                if info is not None and step_type == "update":
                    for prop_name in step["values"]:
                        prop = info.properties.get(prop_name)
                        if prop is not None:
                            what = f"{path} (update {prop_name} on {step[step_type]})"
                            self._check_permissions(
                                prop.requires + prop.set_requires, what
                            )
            for reference in self._references(checked):
                if reference[1:].split(".")[0] not in defined:
                    fail(
                        f'{path}: {reference!r} names no earlier step (give that step "as")'
                    )
            if "as" in step:
                name = step["as"]
                if not isinstance(name, str) or not _STEP_NAME.match(name):
                    fail(
                        f"{path}.as: expected a name of letters, digits and underscores"
                    )
                if name in defined:
                    fail(f"{path}.as: {name!r} already names an earlier step")
                defined.add(name)
        return constructible or {}

    def _check_permissions(self, requires, what):
        try:
            self._mcp.permissions.require(*requires, what=what)
        except PermissionDeniedError as e:
            msg = f"Nothing was applied: {e}"
            raise PermissionDeniedError(msg) from None

    def _info_before_run(self, target, built, graph):
        """The type of a step's target when it is known before the batch
        runs: an object reachable now, or "@name" of a new step."""
        if target.startswith("@") and not target.startswith("@@"):
            return built.get(target[1:])
        try:
            obj, _ = self._object(target.removeprefix("@"), graph)
        except LookupError:
            return None
        return self._info(obj)

    def _follow(self, reference, scope, path):
        """The value an "@name.seg..." reference stands for."""
        name, *segments = reference[1:].split(".")
        value = scope.names[name]
        walked = f"@{name}"
        for segment in segments:
            if is_object(value) or value is self.state:
                prop = self._readable(self._info(value)).get(segment)
                if prop is None:
                    msg = (
                        f"{path}: {walked} (type {self._type(value)}) has no "
                        f"property {segment!r}"
                    )
                    raise NotFoundError(msg)
                value = self._read(value, prop)
                if prop.reference:  # as object_get shows it: objects only
                    if isinstance(value, (list, tuple)):
                        value = [
                            v for v in value if not is_object(v) or self._is_object(v)
                        ]
                    elif is_object(value) and not self._is_object(value):
                        value = None
            elif isinstance(value, dict):
                if segment not in value:
                    msg = f"{path}: {walked} has no key {segment!r}"
                    raise NotFoundError(msg)
                value = value[segment]
            elif isinstance(value, (list, tuple)):
                try:
                    value = value[int(segment)]
                except (ValueError, IndexError):
                    msg = (
                        f"{path}: {walked} has {len(value)} items, no index {segment!r}"
                    )
                    raise NotFoundError(msg) from None
            else:
                type_name = "null" if value is None else type(value).__name__
                msg = f"{path}: {walked} is {type_name}, which has no {segment!r}"
                raise NotFoundError(msg)
            walked = f"{walked}.{segment}"
        return value

    def _substitute(self, value, scope, path, ids=True):
        """``value`` with its references resolved. With ``ids``, objects become their
        ids, since arguments travel as JSON."""
        if isinstance(value, str):
            if value.startswith("@@"):
                return value[1:]
            if value.startswith("@"):
                value = self._follow(value, scope, path)
                return self._as_ids(value) if ids else value
            return value
        if isinstance(value, list):
            return [
                self._substitute(v, scope, f"{path}[{i}]", ids)
                for i, v in enumerate(value)
            ]
        if isinstance(value, dict):
            return {
                k: self._substitute(v, scope, f"{path}.{k}", ids)
                for k, v in value.items()
            }
        return value

    def _as_ids(self, value):
        if is_object(value) or value is self.state:
            return value._id
        if isinstance(value, (list, tuple)):
            return [self._as_ids(v) for v in value]
        if isinstance(value, dict):
            return {k: self._as_ids(v) for k, v in value.items()}
        return value

    def _target(self, target, scope, path):
        """``(object, writable)`` for a step's target: a name, an id, or a
        reference to an object."""
        target = self._substitute(target, scope, path, ids=False)
        graph = self._graph(scope)
        if is_object(target) or target is self.state:
            found = graph.objects.get(target._id)
            if found is None or found[0] is not target:
                msg = f"{path}: {self._label(target)} is not reachable"
                raise NotFoundError(msg)
            return found
        if not isinstance(target, str):
            msg = f"{path}: the target is {type(target).__name__}, not an object"
            raise NotFoundError(msg)
        return self._object(target, graph)

    async def _build(self, info, args, scope, label):
        cls, constructor = info.cls, info.constructor
        self._mcp.permissions.require(
            *constructor.requires, what=f"{type_name(cls)} constructor"
        )
        schema = self._constructor_schema(info)
        if constructor.attr is None:
            values = validate(args or {}, schema, label)
            resolve = self._resolver(scope, read_only=False)
            for name, given in values.items():
                prop = info.properties[name]
                values[name] = from_json(
                    given,
                    prop.type_def,
                    resolve if prop.reference else None,
                    f"{label}.{name}",
                )
            instance = cls(self._mcp.server, **values)
        else:
            fn = getattr(cls, constructor.attr)
            args = bind_arguments(fn, args, schema, label=label, positional=(None,))
            args = self.resolve_arguments(fn, args, scope=scope, label=label)
            instance = fn(self._mcp.server, **args)
            if inspect.isawaitable(instance):
                instance = await instance
        if not isinstance(instance, cls):
            msg = (
                f"{cls.__name__}.{constructor.attr} returned an object of type "
                f"{type(instance).__name__}, not {cls.__name__}"
            )
            raise TypeError(msg)
        scope.built[instance._id] = instance
        await _settle(instance)
        return instance

    async def _run_step(self, step_type, step, scope, path, constructible):
        """Run one step and return its result, which the step's ``as`` can name."""
        if step_type == "new":
            info = constructible[step["new"]]
            label = f"{path}.args"
            args = self._substitute(step.get("args"), scope, label)
            return await self._build(info, args, scope, label)

        obj, writable = self._target(step[step_type], scope, f"{path}.{step_type}")
        if step_type == "update":
            values = self._substitute(step["values"], scope, f"{path}.values")
            return await self._apply_update(obj, writable, values, scope)
        method = self._method(obj, writable, step["method"], step[step_type])
        args = self._substitute(step.get("args"), scope, f"{path}.args")
        raw, _ = await self._invoke(obj, method, args, f"{path}.args", scope)
        return raw

    async def batch(
        self, steps: list[dict], results: Literal["links", "full"] = "links"
    ):
        links = results == "links"
        constructible = self._check_steps(steps)
        scope = _Scope()
        step_results = []
        # Progress counts steps, and a method's own reports count within its step
        reporter = progress.current()
        for index, step in enumerate(steps):
            if index:
                await asyncio.sleep(0)  # a cancel lands between steps
            step_type = next(k for k in _STEP_KEYS if k in step)
            path = f"steps[{index}]"
            try:
                with progress.reporting(progress.batch_step(index, len(steps))):
                    raw = await self._run_step(
                        step_type, step, scope, path, constructible
                    )
            except Exception as e:
                applied = None
                if step_results:
                    applied = self._reply(
                        {"results": step_results},
                        self._graph(scope),
                        links=links,
                        spread=True,
                    )
                failure = _batch_failure(index, step_type, step, e, applied)
                raise BatchError(failure) from e
            step_results.append(raw)
            if "as" in step:
                scope.names[step["as"]] = raw
            if reporter is not None:
                await reporter(index + 1, total=len(steps))
        graph = self._graph()
        unattached = [
            instance
            for instance in scope.built.values()
            if instance._id not in graph.objects
        ]
        result = {"results": step_results}
        if unattached:
            result["unattached"] = unattached
        # Objects as they are once every step ran, each read once
        reply = self._reply(result, self._graph(scope), links=links, spread=True)
        for key in ("results", "unattached"):
            if key in reply.get("more", {}):
                reply["more"][key] += "; run fewer steps per batch"
        return reply

    # -------------------------------------------------------------------------
    # Registration, instructions, audit
    # -------------------------------------------------------------------------

    def _ensure_tools(self):
        if self._registered:
            return
        self._registered = True

        add = self._mcp._add_builtin_tool
        read = {"readOnlyHint": True}
        add(self.list_objects, "object_list", LIST_DESCRIPTION, read)
        add(self.types, "object_types", TYPES_DESCRIPTION, read)
        add(self.get, "object_get", GET_DESCRIPTION, read)
        add(self.update, "object_update", UPDATE_DESCRIPTION, {"idempotentHint": True})
        # call() takes the lock itself, so that each method's option decides
        add(self.call, "object_call", CALL_DESCRIPTION, concurrent=True)
        # The whole batch holds the call lock, once
        add(self.batch, "object_batch", BATCH_DESCRIPTION)

    def instructions(self):
        """The lines the connection instructions give about the objects."""
        try:
            named = self._named(self._graph(), short=True)
        except Exception:
            logger.exception("Listing the objects for the instructions failed")
            return []
        if not named:
            return []

        def label(item):
            text = item["type"] or "empty"
            if item.get("read_only"):
                text += ", read-only"
            if item.get("description"):
                text += f": {item['description']}"
            return text

        items = list(named.items())
        shown = ", ".join(
            f"{name} ({label(item)})" for name, item in items[:MAX_LISTED]
        )
        if len(items) > MAX_LISTED:
            shown += f", and {len(items) - MAX_LISTED} more"
        return [
            f"Objects: {shown}; object_list() lists them, object_types() describes "
            f"their types."
        ]

    def start(self):
        """Called when the server starts: settle the type names, warning about
        collisions. A class defined later is warned about once agents look at types."""
        typeinfo.type_names()

    def audit(self):
        """Log likely exposure mistakes once the app is set up."""
        if not self.exposes_anything():
            return
        try:
            catalog = self._catalog(self._graph())
        except Exception:
            logger.exception("Invalid object exposure")
            return

        permissions = self._mcp.permissions
        for name, info in catalog.items():
            needs = {f"{name}.{m.attr}": m.requires for m in info.methods.values()}
            for prop in info.properties.values():
                needs[f"{name}.{prop.name}"] = prop.requires + prop.set_requires
            if info.constructor is not None:
                needs[f"{name} constructor"] = info.constructor.requires
            for what, requires in needs.items():
                unknown = [n for n in requires if n not in permissions]
                if unknown:
                    logger.warning(
                        "%s requires undeclared permissions %s; it is never offered",
                        what,
                        unknown,
                    )
            for field_name, held in info.hidden_references.items():
                visible = sorted(
                    type_name(k) for t in held for k in subclasses(t) if is_visible(k)
                )
                if visible:
                    logger.warning(
                        "%s.%s holds objects agents see (%s) but is not exposed, so "
                        "they are unreachable through it; expose it, or hide it "
                        "explicitly with mcp=False",
                        name,
                        field_name,
                        ", ".join(visible),
                    )


def _objects_within(value, is_obj, limit=None):
    """The objects in ``value``, at any depth of lists, tuples, sets and dict
    values. ``limit`` keeps the first items of each list or tuple, as a
    capped value shows them."""
    if is_obj(value):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value[:limit]:
            yield from _objects_within(item, is_obj, limit)
    elif isinstance(value, (set, frozenset)):
        for item in value:
            yield from _objects_within(item, is_obj, limit)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _objects_within(item, is_obj, limit)


def _holds_objects(value):
    return next(_objects_within(value, is_object), None) is not None


# -----------------------------------------------------------------------------
# object_types' index
# -----------------------------------------------------------------------------

# The end of a sentence: a period followed by a capital or the end (so not
# "e.g. a"), or by the paragraph's end
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z`(\"']|\s*$)")
MAX_ABOUT = 200


def _first_sentence(text):
    text = " ".join((text or "").split())
    match = _SENTENCE_END.search(text)
    sentence = text[: match.end()] if match else text
    if len(sentence) > MAX_ABOUT:
        sentence = sentence[: MAX_ABOUT - 1] + "…"
    return sentence


def _extending(entry, base_name, base):
    """``entry`` as what it adds to, changes in or drops from ``base``. What it
    lacks is False, including the constructor when it lost the base's."""
    delta = {"extends": base_name}
    if "description" in entry:
        delta["description"] = entry["description"]
    for key in ("properties", "methods"):
        delta[key] = {k: v for k, v in entry[key].items() if base[key].get(k) != v}
        delta[key].update((k, False) for k in base[key] if k not in entry[key])
    if entry.get("constructor") != base.get("constructor"):
        delta["constructor"] = entry.get("constructor", False)
    return delta


def _index_entry(entry):
    """A type as the index lists it: what it extends, the first sentence of its
    description, its own property and method names, those of its base that it
    lacks, and its constructor (False when it lost the base's)."""
    index, lacks = {}, []
    about = _first_sentence(entry.get("description"))
    if about:
        index["about"] = about
    for key in ("properties", "methods"):
        names = [k for k, v in entry.get(key, {}).items() if v is not False]
        lacks.extend(k for k, v in entry.get(key, {}).items() if v is False)
        if names:
            index[key] = names
    if lacks:
        index["lacks"] = lacks
    if "constructor" in entry:
        index["constructor"] = entry["constructor"] is not False
    if "extends" in entry:
        index["extends"] = entry["extends"]
    return index


# -----------------------------------------------------------------------------
# object_batch's results
# -----------------------------------------------------------------------------


def _batch_failure(index, step_type, step, error, results):
    if not isinstance(error, (ValueError, LookupError, PermissionError)):
        logger.error("object_batch step %d raised", index, exc_info=error)
    reason = error_text(error)
    if step_type == "new":
        what = f"new {step['new']}"
    elif step_type == "call":
        what = f"call {step['method']} on {step['call']}"
    else:
        what = f"update {step['update']}"
    message = f"steps[{index}] ({what}) failed: {reason}"
    if not results:  # the first step: its own error says what it did
        return message
    if not message.endswith("."):
        message += "."
    applied = json.dumps(results, default=repr)
    if index == 1:
        return f"{message} Step 0 stays applied (no rollback); its result: {applied}"
    return (
        f"{message} Steps 0-{index - 1} stay applied (no rollback); "
        f"their results: {applied}"
    )


def _is_reference(value) -> bool:
    return isinstance(value, dict) and "id" in value and value.keys() <= {"id", "type"}


def _holds_references(value) -> bool:
    """Whether a rendered value is a reference or a list of them. Those are the
    values an object keeps with ``results: "links"``."""
    if _is_reference(value):
        return True
    return isinstance(value, list) and bool(value) and all(map(_is_reference, value))
