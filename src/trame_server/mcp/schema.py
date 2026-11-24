"""JSON Schema generation from Python type annotations, and validation of
incoming MCP values against the schemas we advertise."""

from __future__ import annotations

import inspect
import json
import re
import types
import typing

from trame_common.obj.mcp import MCPExposable, Progress

__all__ = [
    "ToolError",
    "ValidationError",
    "bind_arguments",
    "docstring",
    "error_text",
    "from_json",
    "function_input_schema",
    "is_object",
    "object_class",
    "parameter_hints",
    "resolve_object_arguments",
    "return_hint",
    "type_to_schema",
    "unwrap",
    "validate",
]

_SCALARS = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    type(None): {"type": "null"},
}


def type_to_schema(annotation, custom=None) -> dict:
    """Best-effort conversion of a type annotation to a JSON Schema fragment.

    Unknown or missing annotations yield ``{}`` (any type). ``custom`` is an
    optional ``annotation -> schema | None`` hook consulted first at every
    level (used to describe references to components and models).

    ``Annotated`` metadata contributes a description (``str``) or extra
    schema keywords (``dict``), e.g.
    ``Annotated[int, "Number of facets", {"minimum": 3, "maximum": 60}]``.
    """
    if annotation is None or annotation is inspect.Parameter.empty:
        return {}

    if custom is not None:
        schema = custom(annotation)
        if schema is not None:
            return schema

    # isinstance first: Annotated metadata may be unhashable (dict schemas)
    if isinstance(annotation, type) and annotation in _SCALARS:
        return dict(_SCALARS[annotation])

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    def convert(a):
        return type_to_schema(a, custom)

    if origin is None:
        if annotation is dict:
            return {"type": "object"}
        if annotation in (list, set, frozenset, tuple):
            return {"type": "array"}
        return {}

    if origin is typing.Annotated:
        schema = convert(args[0])
        for extra in args[1:]:
            if isinstance(extra, str):
                schema["description"] = extra
            elif isinstance(extra, dict):
                schema.update(extra)
        return schema

    if origin is typing.Literal:
        return {"enum": list(args)}

    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        optional = len(non_none) != len(args)
        if len(non_none) == 1:
            schema = convert(non_none[0])
            return nullable(schema) if optional else schema
        variants = [convert(a) for a in non_none]
        if optional:
            variants.append({"type": "null"})
        return {"anyOf": variants}

    if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
        # Fixed-length tuple, e.g. tuple[float, float, float]
        items = [convert(a) for a in args]
        schema = {"type": "array", "minItems": len(items), "maxItems": len(items)}
        if items and all(item == items[0] for item in items):
            schema["items"] = items[0]
        elif items:
            schema["prefixItems"] = items
        return schema

    if origin in (list, set, frozenset, tuple):
        return {"type": "array", "items": convert(args[0]) if args else {}}

    if origin is dict:
        value_schema = convert(args[1]) if len(args) == 2 else {}
        return {"type": "object", "additionalProperties": value_schema}

    return {}


_ARRAYS = (list, tuple, set, frozenset)


def from_json(value, annotation, resolve=None, path="value"):
    """
    ``value``, validated JSON, in the Python shape ``annotation`` declares.
    JSON has no tuples or sets, so arrays become tuples or sets where the
    annotation says so (``tuple[float, float, float]``, ``set[str]``), nested
    in lists, dicts and unions too. Anything else is returned as is.

    With ``resolve``, an id or name given where the annotation names a class
    whose instances agents reach becomes the object: ``resolve(id, cls,
    path)`` returns it or raises. Converting a value twice gives the same
    value, so ids can be resolved after the shape is restored.
    """
    if value is None or annotation is None or annotation is inspect.Parameter.empty:
        return value
    if resolve is not None:
        cls = object_class(annotation)
        if cls is not None:
            return resolve(value, cls, path) if isinstance(value, str) else value
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return from_json(value, args[0], resolve, path)
    if origin in (typing.Union, types.UnionType):
        for arg in args:
            base = (
                typing.get_args(arg)[0]
                if typing.get_origin(arg) is typing.Annotated
                else arg
            )
            container = typing.get_origin(base) or base
            if isinstance(value, str):
                if resolve is not None and object_class(base) is not None:
                    return resolve(value, base, path)
            elif isinstance(value, dict):
                if container is dict:
                    return from_json(value, base, resolve, path)
            elif isinstance(value, _ARRAYS) and container in _ARRAYS:
                return from_json(value, base, resolve, path)
        return value
    if isinstance(value, _ARRAYS):
        if annotation in (tuple, set, frozenset):
            return annotation(value)
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                args = (args[0],) * len(value)
            if len(args) != len(value):
                return tuple(value)
            return tuple(
                from_json(v, a, resolve, f"{path}[{i}]")
                for i, (v, a) in enumerate(zip(value, args, strict=True))
            )
        if origin in (list, set, frozenset) and args:
            items = [
                from_json(v, args[0], resolve, f"{path}[{i}]")
                for i, v in enumerate(value)
            ]
            return items if origin is list else origin(items)
    if isinstance(value, dict) and origin is dict and len(args) == 2:
        return {
            k: from_json(v, args[1], resolve, f"{path}.{k}") for k, v in value.items()
        }
    return value


def nullable(schema: dict) -> dict:
    """Return ``schema`` extended to also accept ``null``."""
    if not schema or _accepts_null(schema):
        return schema
    return {"anyOf": [schema, {"type": "null"}]}


def _accepts_null(schema):
    json_type = schema.get("type")
    if json_type == "null" or (isinstance(json_type, list) and "null" in json_type):
        return True
    return any(_accepts_null(s) for s in schema.get("anyOf", ()))


def parameter_hints(fn):
    """The resolved annotations of ``fn``'s parameters. One annotation that
    cannot be resolved (a forward reference to a later class, typically the
    return type) does not lose the others."""
    try:
        return typing.get_type_hints(fn, include_extras=True)
    except Exception:
        pass
    func = inspect.unwrap(getattr(fn, "__func__", fn))
    globalns = getattr(func, "__globals__", {})
    hints = {}
    for name, annotation in getattr(func, "__annotations__", {}).items():
        if name == "return":
            continue
        holder = types.SimpleNamespace(__annotations__={name: annotation})
        try:
            hints[name] = typing.get_type_hints(
                holder, globalns=globalns, include_extras=True
            )[name]
        except Exception:
            continue
    return hints


def is_progress(annotation) -> bool:
    """True for ``Progress``, ``Progress | None`` and ``Optional[Progress]``
    (Annotated or not): the parameter trame fills in with a reporter."""
    if typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        annotation = args[0] if len(args) == 1 else None
    return isinstance(annotation, type) and issubclass(annotation, Progress)


def progress_parameter(fn):
    """The name of ``fn``'s ``Progress`` parameter, or None."""
    for name, annotation in parameter_hints(fn).items():
        if name != "return" and is_progress(annotation):
            return name
    return None


def check_progress(fn, label):
    """Raise when ``fn`` declares a ``Progress`` parameter but isn't async, since
    reports are awaited."""
    if progress_parameter(fn) is None or inspect.iscoroutinefunction(fn):
        return
    msg = f"{label}: a Progress parameter needs an async function (async def)"
    raise TypeError(msg)


def _json_safe(value):
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def return_hint(fn):
    """The resolved return annotation of ``fn``, or None."""
    try:
        return typing.get_type_hints(fn, include_extras=True).get("return")
    except Exception:
        return None


# A line starting a list item or a field (":param x:"), which keeps its line
# break; the lines indented under it continue it
_ITEM = re.compile(r"\s*(?:[-*+•]|\d+[.)]|:[^:\s][^:]*:)\s")


def unwrap(text):
    """``text`` with the wrapped lines of each paragraph joined, as agents read
    it best. Blank lines, list items, fields and indented blocks (code,
    ``Args:`` sections) keep their line breaks, and so does what is between
    ``` fences."""
    if not text:
        return text
    lines = []
    fenced = False
    # What the next line may continue: top-level prose, or the item at
    # this indent (by lines indented under it)
    prose, item = False, None
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        fence = stripped.startswith("```")
        starts_item = _ITEM.match(line) is not None
        if stripped and not (fenced or fence or starts_item):
            if (item is not None and indent > item) or (prose and indent == 0):
                lines[-1] = f"{lines[-1].rstrip()} {stripped}"
                continue
        lines.append(line)
        fenced ^= fence
        if fenced or fence or not stripped:
            prose, item = False, None
        elif starts_item:
            prose, item = False, indent
        else:
            prose, item = indent == 0, None
    return "\n".join(lines)


def docstring(obj):
    """``obj``'s docstring as agents read it (see :func:`unwrap`), or None."""
    return unwrap(inspect.getdoc(obj))


def function_input_schema(fn, skip=("self",), ref=None) -> dict:
    """Build the MCP ``inputSchema`` for a callable from its signature.
    ``ref`` describes parameters annotated with a component or model class,
    which take the object's id or name (see ``type_to_schema``'s ``custom``). A
    ``Progress`` parameter is trame's to fill in, so agents don't see it."""
    sig = inspect.signature(fn)
    hints = parameter_hints(fn)

    properties = {}
    required = []
    var_keyword = False
    for pname, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            var_keyword = True
            continue
        if pname in skip or param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if is_progress(hints.get(pname)):
            continue
        prop = type_to_schema(hints.get(pname), ref)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
        else:
            if param.default is None:
                prop = nullable(prop)
            if _json_safe(param.default):
                prop["default"] = param.default
        properties[pname] = prop

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    if not var_keyword:
        schema["additionalProperties"] = False
    return schema


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


class ToolError(ValueError):
    """An expected, actionable failure whose message is complete as is: the
    agent reads it without the exception's type name."""


class ValidationError(ToolError):
    """An MCP-supplied value does not match the advertised schema."""


def error_text(error):
    """The text agents read for a failure: the message of a ``ToolError`` or
    ``PermissionError`` as is, else the exception's type and message."""
    if isinstance(error, (ToolError, PermissionError)):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _show(value):
    """``value`` as JSON for a message, the way the agent wrote it."""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def _json_equal(a, b):
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def _check_type(value, json_type, path):
    """Return ``value`` coerced to ``json_type`` (lossless numeric coercion only)."""
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "integer":
        if is_number and isinstance(value, int):
            return value
        if is_number and isinstance(value, float) and value.is_integer():
            return int(value)
    elif json_type == "number":
        if is_number:
            return float(value) if isinstance(value, int) else value
    elif json_type == "string":
        if isinstance(value, str):
            return value
    elif json_type == "boolean":
        if isinstance(value, bool):
            return value
    elif json_type == "null":
        if value is None:
            return value
    elif json_type == "array":
        if isinstance(value, (list, tuple)):
            return list(value)
    elif json_type == "object":
        if isinstance(value, dict):
            return value
    else:
        return value  # unknown type keyword: do not reject

    msg = f"{path}: expected {json_type}, got {_type_name(value)}"
    raise ValidationError(msg)


def validate(value, schema, path="value"):
    """Validate ``value`` against the JSON Schema subset trame generates.

    Returns the value with lossless coercions applied (``3.0`` for an
    integer becomes ``3``, ``3`` for a number becomes ``3.0``); raises
    :class:`ValidationError` naming the offending path otherwise. Keywords
    outside the supported subset are ignored.
    """
    if not schema:
        return value

    branches = schema.get("anyOf") or schema.get("oneOf")
    if branches:
        errors = []
        # A branch of the value's own type first: 3 for float | int stays 3
        exact = _type_name(value)
        branches = sorted(branches, key=lambda b: b.get("type") != exact)
        for branch in branches:
            try:
                value = validate(value, branch, path)
                break
            except ValidationError as e:
                errors.append(str(e).removeprefix(f"{path}: "))
        else:
            msg = f"{path}: does not match any allowed form ({'; '.join(errors)})"
            raise ValidationError(msg)

    if "object" in schema and not isinstance(value, str):
        msg = (
            f"{path}: expected the id of an object of type {schema['object']}, "
            f"got {_type_name(value)}"
        )
        raise ValidationError(msg)

    json_type = schema.get("type")
    if isinstance(json_type, list):
        for candidate in sorted(json_type, key=lambda k: k != _type_name(value)):
            try:
                value = _check_type(value, candidate, path)
                break
            except ValidationError:
                continue
        else:
            msg = f"{path}: expected {' or '.join(json_type)}, got {_type_name(value)}"
            raise ValidationError(msg)
    elif json_type is not None:
        value = _check_type(value, json_type, path)

    if "const" in schema and not _json_equal(value, schema["const"]):
        msg = f"{path}: must be {_show(schema['const'])}"
        raise ValidationError(msg)
    if "enum" in schema and not any(_json_equal(value, e) for e in schema["enum"]):
        choices = ", ".join(_show(e) for e in schema["enum"])
        msg = f"{path}: must be one of {choices}, got {_show(value)}"
        raise ValidationError(msg)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _check_bounds(value, schema, path)
    elif isinstance(value, str):
        _check_string(value, schema, path)
    elif isinstance(value, list):
        value = _check_array(value, schema, path)
    elif isinstance(value, dict):
        value = _check_object(value, schema, path)

    return value


def _check_bounds(value, schema, path):
    checks = (
        ("minimum", lambda v, b: v >= b, "at least"),
        ("maximum", lambda v, b: v <= b, "at most"),
        ("exclusiveMinimum", lambda v, b: v > b, "greater than"),
        ("exclusiveMaximum", lambda v, b: v < b, "less than"),
    )
    for keyword, ok, label in checks:
        if keyword in schema and not ok(value, schema[keyword]):
            msg = f"{path}: must be {label} {schema[keyword]}, got {value}"
            raise ValidationError(msg)


def _check_string(value, schema, path):
    if "minLength" in schema and len(value) < schema["minLength"]:
        msg = f"{path}: must be at least {schema['minLength']} characters"
        raise ValidationError(msg)
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        msg = f"{path}: must be at most {schema['maxLength']} characters"
        raise ValidationError(msg)
    if "pattern" in schema and not re.search(schema["pattern"], value):
        msg = f"{path}: must match pattern {schema['pattern']!r}"
        raise ValidationError(msg)


def _check_array(value, schema, path):
    if "minItems" in schema and len(value) < schema["minItems"]:
        msg = f"{path}: expected at least {schema['minItems']} items, got {len(value)}"
        raise ValidationError(msg)
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        msg = f"{path}: expected at most {schema['maxItems']} items, got {len(value)}"
        raise ValidationError(msg)

    prefix = schema.get("prefixItems", ())
    items = schema.get("items")
    result = []
    for i, item in enumerate(value):
        item_schema = prefix[i] if i < len(prefix) else items
        result.append(
            validate(item, item_schema, f"{path}[{i}]") if item_schema else item
        )
    return result


def _check_object(value, schema, path):
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)

    missing = [k for k in schema.get("required", ()) if k not in value]
    if missing:
        msg = f"{path}: missing required {', '.join(repr(k) for k in missing)}"
        raise ValidationError(msg)

    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{path}: keys must be strings"
            raise ValidationError(msg)
        if key in properties:
            result[key] = validate(item, properties[key], f"{path}.{key}")
        elif additional is False:
            msg = f"{path}: unexpected {key!r}" + (
                f" (allowed: {sorted(properties)})" if properties else ""
            )
            raise ValidationError(msg)
        elif isinstance(additional, dict):
            result[key] = validate(item, additional, f"{path}.{key}")
        else:
            result[key] = item
    return result


def bind_arguments(fn, arguments, schema, label="arguments", positional=()):
    """Validate MCP call arguments for ``fn`` and return the coerced dict.

    Checks them against ``schema`` and against ``fn``'s signature (catching
    missing/unexpected arguments the schema may not describe), so that a
    ``TypeError`` raised later can only come from the function body.
    ``positional`` are the leading arguments the caller supplies itself
    (a constructor's server). Object-typed parameters keep the ids or
    names given; see :func:`resolve_object_arguments`.
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        msg = f"{label}: expected object, got {_type_name(arguments)}"
        raise ValidationError(msg)
    arguments = validate(arguments, schema, label)
    # The Progress parameter is filled in later (see progress.inject)
    reporter = progress_parameter(fn)
    filled = {reporter: None} if reporter and reporter not in arguments else {}
    try:
        inspect.signature(fn).bind(*positional, **arguments, **filled)
    except TypeError as e:
        msg = f"{label}: {e}"
        raise ValidationError(msg) from None
    hints = parameter_hints(fn)
    return {
        name: from_json(value, hints.get(name)) for name, value in arguments.items()
    }


def is_object(value) -> bool:
    """Whether ``value`` is an object agents may reach, once its class declares
    something: an instance of a class that inherits ``MCPExposable``, such as
    a component or a trame-dataclass model."""
    return isinstance(value, MCPExposable)


def object_class(annotation):
    """``annotation`` when it is a class whose instances agents may reach,
    else None."""
    if isinstance(annotation, type) and issubclass(annotation, MCPExposable):
        return annotation
    return None


def object_classes(annotation) -> set:
    """The component and model classes named anywhere in ``annotation``."""
    found, stack = set(), [annotation]
    while stack:
        current = stack.pop()
        cls = object_class(current)
        if cls is not None:
            found.add(cls)
        else:
            stack.extend(typing.get_args(current))
    return found


def resolve_object_arguments(fn, arguments, resolve, label="arguments"):
    """``arguments`` (bound by :func:`bind_arguments`) with the ids or names given
    for object-typed parameters replaced by the objects:
    ``resolve(id, cls, path)`` returns the object or raises."""
    hints = parameter_hints(fn)
    typed = {name for name, hint in hints.items() if object_classes(hint)}
    if not typed & arguments.keys():
        return arguments
    return {
        name: from_json(value, hints[name], resolve, f"{label}.{name}")
        if name in typed
        else value
        for name, value in arguments.items()
    }
