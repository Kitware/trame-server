"""JSON Schemas from type hints, and validation of what agents send."""

import sys
from typing import Annotated, Literal, Optional

import pytest
from trame_common.obj.mcp import MCPExposable

from trame_server.mcp.schema import (
    ToolError,
    ValidationError,
    bind_arguments,
    docstring,
    from_json,
    function_input_schema,
    nullable,
    parameter_hints,
    return_hint,
    type_to_schema,
    unwrap,
    validate,
)


def test_scalars():
    assert type_to_schema(str) == {"type": "string"}
    assert type_to_schema(int) == {"type": "integer"}
    assert type_to_schema(float) == {"type": "number"}
    assert type_to_schema(bool) == {"type": "boolean"}
    assert type_to_schema(type(None)) == {"type": "null"}
    # each call gets its own dict
    type_to_schema(str)["description"] = "changed"
    assert type_to_schema(str) == {"type": "string"}


def test_containers():
    assert type_to_schema(list[int]) == {"type": "array", "items": {"type": "integer"}}
    assert type_to_schema(set[str]) == {"type": "array", "items": {"type": "string"}}
    assert type_to_schema(dict[str, float]) == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }
    assert type_to_schema(list) == {"type": "array"}
    assert type_to_schema(tuple) == {"type": "array"}
    assert type_to_schema(dict) == {"type": "object"}


def test_optional_and_union():
    assert type_to_schema(Optional[int]) == {  # noqa: UP045 - Optional is the point
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }
    assert type_to_schema(int | None) == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }
    assert type_to_schema(int | str) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }
    assert type_to_schema(int | str | None) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]
    }


def test_literal_and_annotated():
    assert type_to_schema(Literal["a", "b"]) == {"enum": ["a", "b"]}
    assert type_to_schema(Literal[1, "a", None]) == {  # noqa: PYI061
        "enum": [1, "a", None]
    }
    assert type_to_schema(Annotated[int, "number of facets"]) == {
        "type": "integer",
        "description": "number of facets",
    }
    assert type_to_schema(Annotated[int, "facets", {"minimum": 3}]) == {
        "type": "integer",
        "description": "facets",
        "minimum": 3,
    }


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Python 3.10 hashes a union's members, and a dict can't be hashed",
)
def test_annotated_in_a_union():
    assert type_to_schema(Annotated[float, {"minimum": 0}] | None) == {
        "anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]
    }


def test_fixed_length_tuples():
    assert type_to_schema(tuple[float, float, float]) == {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }
    # JSON Schema 2020-12: positional items are prefixItems
    assert type_to_schema(tuple[str, int]) == {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}],
        "minItems": 2,
        "maxItems": 2,
    }
    assert type_to_schema(tuple[int, ...]) == {
        "type": "array",
        "items": {"type": "integer"},
    }


def test_the_empty_tuple():
    assert type_to_schema(tuple[()]) == {"type": "array", "minItems": 0, "maxItems": 0}


def test_unknown_types_degrade_to_any():
    class Custom:
        pass

    assert type_to_schema(Custom) == {}
    assert type_to_schema(None) == {}
    assert type_to_schema(Optional[Custom]) == {}  # noqa: UP045


def test_a_custom_hook_is_consulted_at_every_level():
    class Point:
        pass

    def custom(annotation):
        return (
            {"type": "string", "description": "a point id"}
            if annotation is Point
            else None
        )

    assert type_to_schema(list[Point], custom) == {
        "type": "array",
        "items": {"type": "string", "description": "a point id"},
    }
    assert type_to_schema(dict[str, Point | None], custom)["additionalProperties"] == {
        "anyOf": [{"type": "string", "description": "a point id"}, {"type": "null"}]
    }
    assert type_to_schema(int, custom) == {"type": "integer"}


def test_nullable():
    assert nullable({"type": "integer"}) == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }
    for schema in (
        {},
        {"type": "null"},
        {"type": ["string", "null"]},
        {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    ):
        assert nullable(schema) is schema


def test_function_input_schema():
    def fn(resolution: int, label: str = "cone", factor: float | None = None) -> str:  # noqa: ARG001
        return label

    schema = function_input_schema(fn)
    assert schema["type"] == "object"
    assert schema["required"] == ["resolution"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["resolution"] == {"type": "integer"}
    assert schema["properties"]["label"] == {"type": "string", "default": "cone"}
    assert schema["properties"]["factor"]["default"] is None


def test_function_input_schema_none_default_is_nullable():
    def fn(count: int = None):  # noqa: RUF013 - implicit Optional is the point
        return count

    assert function_input_schema(fn)["properties"]["count"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
        "default": None,
    }


def test_function_input_schema_leaves_out_defaults_json_cannot_hold():
    marker = object()

    def fn(value: int = marker, items: tuple = (1, 2)):  # noqa: ARG001
        return value

    properties = function_input_schema(fn)["properties"]
    assert properties["value"] == {"type": "integer"}
    assert properties["items"] == {"type": "array", "default": (1, 2)}


def test_function_input_schema_without_parameters():
    def fn():
        pass

    assert function_input_schema(fn) == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_function_input_schema_var_keyword_allows_extras():
    def fn(a: int, *args, **options):  # noqa: ARG001
        return a

    schema = function_input_schema(fn)
    assert "additionalProperties" not in schema
    assert list(schema["properties"]) == ["a"]


def test_function_input_schema_skips_self():
    class App:
        def method(self, value: int):
            pass

    assert list(function_input_schema(App.method)["properties"]) == ["value"]
    assert list(function_input_schema(App().method)["properties"]) == ["value"]


def test_an_unresolvable_hint_does_not_lose_the_others():
    def fn(a: int, b: "Missing" = None) -> "AlsoMissing":  # noqa: ARG001, F821
        return a

    assert parameter_hints(fn) == {"a": int}
    assert return_hint(fn) is None
    schema = function_input_schema(fn)
    assert schema["properties"] == {"a": {"type": "integer"}, "b": {"default": None}}


def test_return_hint():
    def fn() -> Annotated[int, "count"]:
        return 1

    assert return_hint(fn) == Annotated[int, "count"]


def test_validate_scalars_and_coercion():
    assert validate(3, {"type": "integer"}) == 3
    assert validate(3.0, {"type": "integer"}) == 3
    assert isinstance(validate(3.0, {"type": "integer"}), int)
    assert isinstance(validate(3, {"type": "number"}), float)
    for value, schema in (
        (3.5, {"type": "integer"}),
        (True, {"type": "integer"}),
        (True, {"type": "number"}),
        (1, {"type": "boolean"}),
        ("3", {"type": "integer"}),
        (None, {"type": "string"}),
        (float("inf"), {"type": "integer"}),
    ):
        with pytest.raises(ValidationError):
            validate(value, schema)


def test_a_validation_error_is_a_complete_tool_error():
    assert issubclass(ValidationError, ToolError)
    assert issubclass(ToolError, ValueError)
    with pytest.raises(ValidationError, match=r"^count: expected integer, got string$"):
        validate("x", {"type": "integer"}, "count")


def test_validate_unknown_and_empty_schemas_accept_anything():
    assert validate({"x": [1]}, {}) == {"x": [1]}
    assert validate("x", {"description": "no type", "model": "Person"}) == "x"
    assert validate("x", {"type": "unknown-keyword"}) == "x"


def test_validate_containers_report_paths():
    schema = type_to_schema(dict[str, list[float]])
    assert validate({"a": [1, 2.5]}, schema) == {"a": [1.0, 2.5]}
    with pytest.raises(
        ValidationError, match=r"^value\.a\[1\]: expected number, got string$"
    ):
        validate({"a": [1, "x"]}, schema)

    schema = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }
    with pytest.raises(
        ValidationError, match=r"^color: expected at least 3 items, got 2$"
    ):
        validate([1, 2], schema, "color")
    with pytest.raises(
        ValidationError, match=r"^color: expected at most 3 items, got 4$"
    ):
        validate([1, 2, 3, 4], schema, "color")

    schema = type_to_schema(tuple[str, int])
    assert validate(["a", 2.0], schema) == ["a", 2]
    with pytest.raises(
        ValidationError, match=r"^value\[1\]: expected integer, got string$"
    ):
        validate(["a", "b"], schema)


def test_validate_objects():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    }
    assert validate({"a": 1.0, "b": "x"}, schema) == {"a": 1, "b": "x"}
    with pytest.raises(ValidationError, match=r"^value: missing required 'a', 'b'$"):
        validate({}, schema)
    with pytest.raises(
        ValidationError, match=r"^value: unexpected 'c' \(allowed: \['a', 'b'\]\)$"
    ):
        validate({"a": 1, "b": "x", "c": 3}, schema)
    with pytest.raises(ValidationError, match="keys must be strings"):
        validate({1: 1}, {"type": "object"})

    extras = {"type": "object", "additionalProperties": {"type": "number"}}
    assert validate({"x": 1}, extras) == {"x": 1.0}
    with pytest.raises(ValidationError, match=r"^value\.x: expected number"):
        validate({"x": "1"}, extras)


def test_validate_bounds():
    assert validate(0.5, {"type": "number", "minimum": 0, "maximum": 1}) == 0.5
    with pytest.raises(ValidationError, match=r"^value: must be at most 1, got 2\.5$"):
        validate(2.5, {"type": "number", "maximum": 1})
    with pytest.raises(ValidationError, match=r"^value: must be at least 3, got 1$"):
        validate(1, {"type": "integer", "minimum": 3})
    with pytest.raises(
        ValidationError, match=r"^value: must be greater than 0, got 0$"
    ):
        validate(0, {"exclusiveMinimum": 0})
    with pytest.raises(ValidationError, match=r"^value: must be less than 1, got 1$"):
        validate(1, {"exclusiveMaximum": 1})


def test_validate_strings():
    schema = {"type": "string", "minLength": 2, "maxLength": 4, "pattern": "^[a-z]+$"}
    assert validate("abc", schema) == "abc"
    with pytest.raises(ValidationError, match="at least 2 characters"):
        validate("a", schema)
    with pytest.raises(ValidationError, match="at most 4 characters"):
        validate("abcde", schema)
    with pytest.raises(ValidationError, match="must match pattern"):
        validate("ABC", schema)


def test_enum_and_const_quote_values_as_json():
    with pytest.raises(ValidationError) as error:
        validate("cubes", {"enum": ["surface", "wireframe"]}, "arguments.mode")
    assert str(error.value) == (
        'arguments.mode: must be one of "surface", "wireframe", got "cubes"'
    )
    with pytest.raises(ValidationError) as error:
        validate(3, {"enum": [1, None, True]})
    assert str(error.value) == "value: must be one of 1, null, true, got 3"
    with pytest.raises(ValidationError) as error:
        validate("b", {"const": "a"})
    assert str(error.value) == 'value: must be "a"'

    assert validate("a", {"const": "a"}) == "a"
    assert validate(1, {"enum": [1, 2]}) == 1
    # True must not match 1, as in JSON
    with pytest.raises(ValidationError):
        validate(True, {"enum": [1, 2]})
    with pytest.raises(ValidationError):
        validate(1, {"const": True})


def test_validate_unions():
    schema = type_to_schema(int | str)
    assert validate("a", schema) == "a"
    with pytest.raises(ValidationError) as error:
        validate([1], schema)
    assert str(error.value) == (
        "value: does not match any allowed form "
        "(expected integer, got array; expected string, got array)"
    )
    assert validate(None, type_to_schema(Optional[int])) is None  # noqa: UP045
    assert validate(2, {"oneOf": [{"type": "string"}, {"type": "integer"}]}) == 2

    assert validate("on", {"type": ["boolean", "string"]}) == "on"
    with pytest.raises(
        ValidationError, match=r"^value: expected boolean or string, got integer$"
    ):
        validate(1, {"type": ["boolean", "string"]})


def test_bind_arguments_checks_schema_and_signature():
    def fn(a: int, b: str = "x"):  # noqa: ARG001
        return a

    schema = function_input_schema(fn)
    assert bind_arguments(fn, {"a": 1.0}, schema) == {"a": 1}
    assert bind_arguments(lambda: None, None, {}) == {}
    with pytest.raises(
        ValidationError, match=r"^arguments: expected object, got array$"
    ):
        bind_arguments(fn, [1], schema)
    with pytest.raises(ValidationError, match="unexpected 'c'"):
        bind_arguments(fn, {"a": 1, "c": 2}, schema)

    # a permissive hand-written schema still cannot smuggle unknown arguments
    with pytest.raises(ValidationError, match="unexpected keyword argument"):
        bind_arguments(fn, {"a": 1, "c": 2}, {"type": "object"})
    with pytest.raises(ValidationError, match=r"^args: missing a required argument"):
        bind_arguments(fn, {}, {"type": "object"}, label="args")


def test_bind_arguments_takes_leading_positional_arguments():
    def build(server, size: int):
        return server, size

    schema = function_input_schema(build, skip=("server",))
    assert bind_arguments(build, {"size": 2}, schema, positional=("srv",)) == {
        "size": 2
    }
    with pytest.raises(ValidationError, match="missing a required argument: 'size'"):
        bind_arguments(build, {}, {"type": "object"}, positional=("srv",))


def test_from_json_restores_declared_tuples():
    Vector = tuple[float, float, float]
    assert from_json([1.0, 2.0, 3.0], Vector) == (1.0, 2.0, 3.0)
    assert from_json([[0, 1], [2, 3]], list[tuple[int, int]]) == [(0, 1), (2, 3)]
    assert from_json([1, 2, 3], tuple[int, ...]) == (1, 2, 3)
    assert from_json([1, 2], tuple) == (1, 2)
    assert from_json({"a": [1, 2]}, dict[str, tuple[int, int]]) == {"a": (1, 2)}
    assert from_json([1.0, 2.0, 3.0], Vector | None) == (1.0, 2.0, 3.0)
    assert from_json(None, Vector | None) is None
    assert from_json([1.0, 2.0, 3.0], Annotated[Vector, "a point"]) == (1.0, 2.0, 3.0)
    assert from_json([1.0, 2.0, 3.0], Annotated[Vector, "a point"] | None) == (
        1.0,
        2.0,
        3.0,
    )
    assert from_json([1.0, 2.0, 3.0], Optional[Annotated[Vector, "p"]]) == (  # noqa: UP045
        1.0,
        2.0,
        3.0,
    )
    assert from_json({"a": [1, 2]}, dict[str, tuple[int, int]] | None) == {"a": (1, 2)}
    # anything else is left alone
    assert from_json([1, 2], list[int]) == [1, 2]
    assert from_json([1, 2], list) == [1, 2]
    assert from_json("x", Vector) == "x"
    assert from_json("x", Vector | str) == "x"
    assert from_json([1, 2], None) == [1, 2]


def test_tool_arguments_get_their_declared_tuples():
    def place(position: tuple[float, float, float], tags: list[str] | None = None):
        return position, tags

    schema = function_input_schema(place)
    arguments = bind_arguments(place, {"position": [1, 2, 3], "tags": ["a"]}, schema)
    assert arguments == {"position": (1.0, 2.0, 3.0), "tags": ["a"]}
    assert isinstance(arguments["position"], tuple)


def test_from_json_restores_declared_sets():
    assert from_json(["a", "b", "a"], set[str]) == {"a", "b"}
    assert from_json([1, 2], frozenset[int]) == frozenset({1, 2})
    assert from_json([1, 2], set) == {1, 2}
    assert from_json({"k": ["a"]}, dict[str, set[str]] | None) == {"k": {"a"}}


class Thing(MCPExposable):
    pass


def test_from_json_resolves_ids_where_objects_are_declared():
    things = {"0x1": "one", "0x2": "two"}
    seen = []

    def resolve(value, cls, path):
        seen.append((value, cls, path))
        return things[value]

    assert from_json("0x1", Thing, resolve) == "one"
    assert from_json(["0x1", "0x2"], list[Thing], resolve, "args.items") == [
        "one",
        "two",
    ]
    assert seen[-1] == ("0x2", Thing, "args.items[1]")
    assert from_json({"a": "0x2"}, dict[str, Thing] | None, resolve, "v") == {
        "a": "two"
    }
    assert seen[-1] == ("0x2", Thing, "v.a")
    assert from_json("0x1", Annotated[Thing, "The thing"] | None, resolve) == "one"
    # Without resolve, ids stay as given; a second pass resolves them
    shaped = from_json(["0x1"], set[Thing])
    assert shaped == {"0x1"}
    assert from_json(shaped, set[Thing], resolve) == {"one"}


# -----------------------------------------------------------------------------
# Docstrings
# -----------------------------------------------------------------------------


def test_wrapped_lines_are_joined_paragraphs_kept():
    assert unwrap("Orient the camera so\nthis axis points up.") == (
        "Orient the camera so this axis points up."
    )
    assert unwrap("One that\nwraps.\n\nTwo that\nwraps.") == (
        "One that wraps.\n\nTwo that wraps."
    )
    assert unwrap(None) is None


def test_lists_fields_and_indented_blocks_keep_their_breaks():
    assert unwrap("Modes:\n- fast, which\n  wraps\n- slow\n1. one\n2) two") == (
        "Modes:\n- fast, which wraps\n- slow\n1. one\n2) two"
    )
    assert unwrap("Load.\n\n:param path: the path\n    to it\n:returns: it") == (
        "Load.\n\n:param path: the path to it\n:returns: it"
    )
    assert unwrap("Args:\n    x: the x\n    y: the y\nThen prose\ngoes on.") == (
        "Args:\n    x: the x\n    y: the y\nThen prose goes on."
    )
    assert unwrap("Run:\n```\na = 1\nb = 2\n```\nafter the\nfence.") == (
        "Run:\n```\na = 1\nb = 2\n```\nafter the fence."
    )


def test_docstring():
    def documented():
        """Reset the camera so
        everything shows.

        Keeps the view up.
        """

    assert docstring(documented) == (
        "Reset the camera so everything shows.\n\nKeeps the view up."
    )
    assert docstring(lambda: None) is None
