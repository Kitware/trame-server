"""The object layer with components and the state object (models are tested
in trame-dataclass)."""

import asyncio
import gc
import itertools
import json
import logging
from typing import Annotated, Literal

import pytest
from trame.app import TrameComponent, get_server
from trame_common.decorators import mcp
from trame_common.obj.mcp import MCPExposable

from trame_server.mcp.objects import OBJECT_TOOLS

_counter = itertools.count()


@pytest.fixture
def server():
    server = get_server(f"test_mcp_objects_{next(_counter)}")
    server.mcp.enabled = True
    return server


async def call(server, name, **arguments):
    """``(value, is_error)`` of a tools/call, as an agent reads it."""
    response = await server.mcp.protocol.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    result = response["result"]
    content = result["content"]
    text = content[0]["text"] if content else None
    try:
        value = json.loads(text) if text is not None else None
    except json.JSONDecodeError:
        value = text
    return value, bool(result.get("isError"))


async def ok(server, name, **arguments):
    value, error = await call(server, name, **arguments)
    assert not error, value
    return value


async def fails(server, name, **arguments):
    value, error = await call(server, name, **arguments)
    assert error, value
    return value


def read(reply):
    """The object a reply's result refers to, as its entry plus its id."""
    obj_id = reply["result"]["id"]
    return {"id": obj_id, **reply["objects"][obj_id]}


# -----------------------------------------------------------------------------
# Classes (names are process-wide for agents: keep them unique in the suite)
# -----------------------------------------------------------------------------


class Viewport(TrameComponent):
    """A 3D view of the scene. It shows what is loaded."""

    def __init__(self, server, background="black"):
        super().__init__(server)
        self._background = background
        self.calls = []

    @mcp.method
    def set_view_up(self, axis: Literal["x", "y", "z"]) -> str:
        """Orient the camera so this axis points up."""
        self.calls.append(axis)
        return f"up {axis}"

    @mcp.method(read_only=True)
    def describe_view(self) -> dict:
        """What the view shows."""
        return {"background": self._background}

    @mcp.method
    async def wait(self, seconds: Annotated[float, {"minimum": 0}] = 0) -> str:
        return f"waited {seconds}"

    @mcp.method(read_only=True)
    def echo(self, value: float | int | str) -> str:  # noqa: PYI041 (the point)
        return f"{type(value).__name__} {value}"

    @mcp.property
    def background(self) -> Annotated[str, "Background color"]:
        return self._background

    @background.setter
    def background(self, value):
        if value == "boom":
            msg = "cannot"
            raise RuntimeError(msg)
        self._background = value

    @mcp.property
    def size(self) -> int:
        """Pixels across."""
        return 300


class Desk(TrameComponent):
    """Holds the viewports."""

    def __init__(self, server):
        super().__init__(server)
        self.views = []

    @mcp.property
    def active(self) -> Viewport | None:
        return self.views[0] if self.views else None

    @mcp.method
    def pick(self, view: Viewport) -> Viewport:
        """Make a viewport the active one."""
        self.views.remove(view)
        self.views.insert(0, view)
        return view


class Plain(TrameComponent):
    def do(self): ...


class Locked(Viewport, mcp=False):
    pass


# -----------------------------------------------------------------------------
# Exposure
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reached_once_named(server):
    view = Viewport(server)
    assert "object_get" not in server.mcp._tools  # built is not exposed

    view.mcp_expose("view")
    assert set(OBJECT_TOOLS) <= set(server.mcp._tools)

    assert await ok(server, "object_list") == {
        "objects": {"view": {"type": "Viewport"}}
    }
    index = await ok(server, "object_types")
    assert index["types"]["Viewport"] == {
        "about": "A 3D view of the scene.",
        "properties": ["background", "size"],
        "methods": ["set_view_up", "describe_view", "wait", "echo"],  # as defined
    }

    value = await ok(server, "object_get", target=view._id)
    assert value == {
        "result": {"id": view._id},
        "objects": {
            view._id: {
                "type": "Viewport",
                "names": ["view"],
                "values": {"background": "black", "size": 300},
            }
        },
    }


@pytest.mark.asyncio
async def test_names(server):
    left, right = Viewport(server), Viewport(server)
    left.mcp_expose("left")
    left.mcp_expose("main")
    right.mcp_expose("right")

    value = read(await ok(server, "object_get", target="main"))
    assert value["id"] == left._id
    assert value["names"] == ["left", "main"]
    assert (await ok(server, "object_list"))["objects"] == {
        "left": {"type": "Viewport"},
        "main": {"type": "Viewport"},
        "right": {"type": "Viewport"},
    }

    with pytest.raises(ValueError, match="starts with a letter"):
        left.mcp_expose("1st")
    with pytest.raises(ValueError, match="reserved"):
        left.mcp_expose("state")
    with pytest.raises(TypeError, match="declares nothing"):
        server.mcp.expose_object(Plain(server), "plain")
    with pytest.raises(TypeError, match="takes a component"):
        server.mcp.expose_object(3, "three")

    server.mcp.unexpose_object("main")
    assert read(await ok(server, "object_get", target="left"))["names"] == ["left"]
    with pytest.raises(KeyError):
        server.mcp.unexpose_object("main")

    message = await fails(server, "object_get", target="viewer")
    assert message == (
        'Unknown object "viewer". Objects: left, right (or an object id); '
        "object_list() lists them all."
    )


@pytest.mark.asyncio
async def test_getter_follows_reassignment(server):
    first, second = Viewport(server, "red"), Viewport(server, "blue")
    holder = {"active": first}
    server.mcp.expose_object(lambda: holder["active"], "active_viewer")

    value = await ok(server, "object_get", target="active_viewer")
    assert value["result"] == {"id": first._id}
    holder["active"] = second
    value = await ok(server, "object_get", target="active_viewer")
    assert value["result"] == {"id": second._id}
    holder["active"] = None
    message = await fails(server, "object_get", target="active_viewer")
    assert "currently empty" in message


@pytest.mark.asyncio
async def test_unexpose_and_unbind(server):
    view = Viewport(server)
    view.mcp_expose("view")
    view.mcp_unexpose()
    assert "Unknown object" in await fails(server, "object_get", target=view._id)
    assert "Unknown object" in await fails(server, "object_get", target="view")

    other = Viewport(server)
    other.mcp_expose("other")
    await ok(server, "object_get", target=other._id)
    other._unbind_annotated_methods()
    assert "Unknown object" in await fails(server, "object_get", target=other._id)


@pytest.mark.asyncio
async def test_components_are_held_weakly(server):
    view = Viewport(server)
    view.mcp_expose("view")
    _id = view._id
    del view
    gc.collect()
    assert await ok(server, "object_list") == {"objects": {"view": {"type": None}}}
    assert "Unknown object" in await fails(server, "object_get", target=_id)
    Viewport(server).mcp_expose("view")  # the name is free again


class Lens(MCPExposable, mcp={"description": "A camera lens"}):
    """A plain class: it mixes in MCPExposable, with no server of its own."""

    def __init__(self):
        self._zoom = 1.0

    @mcp.property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, value: float):
        self._zoom = value

    @mcp.method
    def reset(self) -> str:
        """Zoom back out."""
        self._zoom = 1.0
        return "Reset"


@pytest.mark.asyncio
async def test_any_class_can_mix_in_exposable(server):
    server.mcp.expose_object(Lens(), "lens")
    gc.collect()  # held: unlike a component's, nothing else keeps it alive
    await ok(server, "object_update", target="lens", values={"zoom": 2.5})
    assert read(await ok(server, "object_get", target="lens"))["values"] == {
        "zoom": 2.5
    }
    assert await ok(server, "object_call", target="lens", method="reset") == "Reset"
    described = (await ok(server, "object_types", type_names=["Lens"]))["types"]
    assert described["Lens"]["description"] == "A camera lens"

    class Leaky(MCPExposable, mcp={"methods": ["mcp_expose"]}):
        pass

    with pytest.raises(ValueError, match="part of trame's API"):
        server.mcp.describe(Leaky)


class Shelf(TrameComponent):
    """Holds viewports in nested containers."""

    def __init__(self, server):
        super().__init__(server)
        self._rows = {"top": [Viewport(server), Viewport(server)]}

    @mcp.property
    def rows(self) -> dict[str, list[Viewport]]:
        return self._rows

    @mcp.method(read_only=True)
    def distinct(self) -> set[Viewport]:
        """The viewports, once each."""
        return set(self._rows["top"])


@pytest.mark.asyncio
async def test_objects_nested_in_containers_are_reached(server):
    shelf = Shelf(server)
    shelf.mcp_expose("shelf")
    top = [view._id for view in shelf._rows["top"]]
    reply = await ok(server, "object_get", target="shelf", depth=2)
    rows = read(reply)["values"]["rows"]
    assert sorted(ref["id"] for ref in rows["top"]) == sorted(top)
    assert set(top) <= reply["objects"].keys()
    assert read(await ok(server, "object_get", target=top[0]))["id"] == top[0]

    # A set of objects comes back as references too, not as text
    reply = await ok(server, "object_call", target="shelf", method="distinct")
    assert sorted(ref["id"] for ref in reply["result"]) == sorted(top)


@pytest.mark.asyncio
async def test_a_name_exposes_one_object(server, caplog):
    view, other = Viewport(server), Viewport(server)
    with pytest.raises(TypeError, match="each under its own name"):
        server.mcp.expose_object([view, other], "views")

    view.mcp_expose("view", description="The main view.")
    view.mcp_expose("view", read_only=True)  # the same object: new options
    listed = (await ok(server, "object_list"))["objects"]
    assert listed["view"] == {"type": "Viewport", "read_only": True}
    with pytest.raises(ValueError, match=f"'view' already exposes Viewport {view._id}"):
        other.mcp_expose("view")

    def active():
        return other

    server.mcp.expose_object(active, "active")
    server.mcp.expose_object(active, "active", read_only=True)
    with pytest.raises(ValueError, match="'active' already exposes a function"):
        server.mcp.expose_object(lambda: other, "active")

    # Withdrawn, the name is free
    view.mcp_unexpose()
    other.mcp_expose("view")
    assert read(await ok(server, "object_get", target="view"))["id"] == other._id

    # A function returning something else exposes nothing
    server.mcp.expose_object(lambda: [view], "listed")
    listed = (await ok(server, "object_list"))["objects"]
    assert listed["listed"] == {"type": None}
    assert "'listed' exposes a list" in caplog.text


@pytest.mark.asyncio
async def test_descriptions(server):
    left, right = Viewport(server), Viewport(server)
    left.mcp_expose("left", description="The view on the left. It shows the input.")
    right.mcp_expose("right", description="The view on the right.", read_only=True)
    listed = (await ok(server, "object_list"))["objects"]
    assert listed == {
        "left": {
            "type": "Viewport",
            "description": "The view on the left. It shows the input.",
        },
        "right": {
            "type": "Viewport",
            "read_only": True,
            "description": "The view on the right.",
        },
    }

    # The connection instructions keep the first sentence
    response = await server.mcp.protocol.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert (
        "Objects: left (Viewport: The view on the left.), right (Viewport, "
        "read-only: The view on the right.); object_list() lists them"
        in response["result"]["instructions"]
    )

    with pytest.raises(TypeError, match="description must be a string"):
        left.mcp_expose("main", description=3)


# -----------------------------------------------------------------------------
# Read-only
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_component(server):
    view = Viewport(server)
    view.mcp_expose("view", read_only=True)

    for target in ("view", view._id):
        value = read(await ok(server, "object_get", target=target))
        assert value["read_only"] is True
        message = await fails(
            server,
            "object_call",
            target=target,
            method="set_view_up",
            args={"axis": "y"},
        )
        assert "read-only" in message
        assert "describe_view" in message
        assert await ok(server, "object_call", target=target, method="describe_view")
        message = await fails(
            server, "object_update", target=target, values={"background": "white"}
        )
        assert "read-only" in message
    assert view.calls == []

    # A writable name wins
    view.mcp_expose("editable")
    assert await ok(
        server, "object_call", target=view._id, method="set_view_up", args={"axis": "x"}
    )


@pytest.mark.asyncio
async def test_read_only_function_covers_its_result(server):
    views = [Viewport(server), Viewport(server)]
    server.mcp.expose_object(lambda: views[0], "first", read_only=True)

    message = await fails(
        server,
        "object_call",
        target=views[0]._id,
        method="set_view_up",
        args={"axis": "y"},
    )
    assert "read-only" in message
    listed = (await ok(server, "object_list"))["objects"]
    assert listed == {"first": {"type": "Viewport", "read_only": True}}
    assert "Unknown object" in await fails(
        server, "object_get", target=views[1]._id
    )  # not what it returns

    # A writable name wins
    views[0].mcp_expose("editable")
    assert await ok(
        server,
        "object_call",
        target=views[0]._id,
        method="set_view_up",
        args={"axis": "x"},
    )


# -----------------------------------------------------------------------------
# object_list and object_types
# -----------------------------------------------------------------------------


class Base3D(TrameComponent):
    """The base of 3D things."""

    @mcp.method
    def reset(self) -> None:
        """Back to defaults."""

    @mcp.property
    def shape(self) -> str:
        return "base"


class Derived3D(Base3D):
    @mcp.method
    def spin(self, turns: int = 1) -> None:
        """Spin it."""


@pytest.mark.asyncio
async def test_describe_types_and_members(server):
    derived = Derived3D(server)
    derived.mcp_expose("thing")

    index = await ok(server, "object_types")
    assert index["types"]["Derived3D"] == {"methods": ["spin"], "extends": "Base3D"}
    assert index["types"]["Base3D"] == {
        "about": "The base of 3D things.",
        "properties": ["shape"],
        "methods": ["reset"],
    }

    full = await ok(server, "object_types", type_names=["Derived3D"])
    assert full["types"]["Derived3D"] == {
        "extends": "Base3D",
        "properties": {},
        "methods": {
            "spin": {
                "description": "Spin it.",
                "parameters": {
                    "type": "object",
                    "properties": {"turns": {"type": "integer", "default": 1}},
                    "additionalProperties": False,
                },
            }
        },
    }
    inherited = await ok(
        server, "object_types", type_names=["Derived3D"], include_inherited=True
    )
    assert set(inherited["types"]["Derived3D"]["methods"]) == {"reset", "spin"}
    assert inherited["types"]["Derived3D"]["properties"]["shape"] == {
        "type": "string",
        "read_only": True,
    }

    member = await ok(server, "object_types", type_names=["Base3D.reset"])
    assert member == {
        "types": {
            "Base3D": {
                "methods": {
                    "reset": {
                        "description": "Back to defaults.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    }
                }
            }
        }
    }
    # Types only: an object's name is unknown here
    message = await fails(server, "object_types", type_names=["thing"])
    assert "Unknown types or members: thing" in message

    # Every wrong name, in one reply
    message = await fails(server, "object_types", type_names=["Nope", "Base3D.nope"])
    assert "Unknown types or members: Nope" in message
    assert "No member Base3D.nope" in message


@pytest.mark.asyncio
async def test_describe_parameters_and_returns(server):
    desk = Desk(server)
    desk.mcp_expose("desk")
    described = await ok(server, "object_types", type_names=["Desk"])
    desk = described["types"]["Desk"]
    # Object-typed values read the same everywhere: {"object": "T"}
    assert desk["properties"]["active"] == {
        "anyOf": [{"object": "Viewport"}, {"type": "null"}],
        "read_only": True,
    }
    pick = desk["methods"]["pick"]
    assert pick["parameters"]["properties"]["view"] == {"object": "Viewport"}
    assert pick["returns"] == {"object": "Viewport"}


def test_server_describe(server):
    assert server.mcp.describe(Plain) is None
    described = server.mcp.describe(Viewport)
    assert described["properties"]["background"] == {
        "type": "string",
        "description": "Background color",
    }
    assert described["properties"]["size"]["read_only"] is True
    assert described["methods"]["wait"]["parameters"]["properties"]["seconds"] == {
        "type": "number",
        "minimum": 0,
        "default": 0,
    }


@pytest.mark.asyncio
async def test_type_name_collision(server, caplog):
    def make():
        class Shared(TrameComponent):
            @mcp.method
            def go(self): ...

        return Shared

    first, second = make(), make()
    a, b = first(server), second(server)
    a.mcp_expose("a")
    b.mcp_expose("b")
    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        listed = (await ok(server, "object_list"))["objects"]
    assert listed["a"]["type"] == "Shared"
    qualified = listed["b"]["type"]
    assert qualified.startswith("test_mcp_objects.") or qualified.endswith(".Shared")
    assert qualified != "Shared"
    assert "Two classes agents see are named Shared" in caplog.text


@pytest.mark.asyncio
async def test_type_name_collision_after_start(server, caplog):
    server.mcp._start()

    def make():
        class Latecomer(TrameComponent):
            @mcp.method
            def go(self): ...

        return Latecomer

    first, second = make(), make()
    late = first(server)
    late.mcp_expose("late")
    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        await ok(server, "object_types")  # warned once agents look at types
    assert "Two classes agents see are named Latecomer" in caplog.text
    assert first is not second


# -----------------------------------------------------------------------------
# Class options
# -----------------------------------------------------------------------------


class Holder(TrameComponent, mcp={"description": "Holds things.", "all_methods": True}):
    def visible(self) -> str:
        return "yes"

    def _private(self): ...

    @property
    def count(self) -> int:
        return 3

    @mcp.method
    def also(self): ...


class Wide(Holder, mcp={"methods": {"visible": False}, "properties": ["count"]}):
    pass


@pytest.mark.asyncio
async def test_class_options(server):
    built = [Holder(server), Wide(server)]  # held: names hold them weakly
    for i, obj in enumerate(built):
        obj.mcp_expose(f"thing_{i}")
    described = await ok(server, "object_types", type_names=["Holder", "Wide"])
    holder = described["types"]["Holder"]
    assert holder["description"] == "Holds things."
    assert set(holder["methods"]) == {"also", "visible"}
    assert holder["properties"] == {}
    # What a subclass drops of its base is false
    wide = described["types"]["Wide"]
    assert wide == {
        "extends": "Holder",
        "properties": {"count": {"type": "integer", "read_only": True}},
        "methods": {"visible": False},
    }
    index = (await ok(server, "object_types"))["types"]["Wide"]
    assert index == {"properties": ["count"], "lacks": ["visible"], "extends": "Holder"}
    described = await ok(
        server, "object_types", type_names=["Wide"], include_inherited=True
    )
    assert set(described["types"]["Wide"]["methods"]) == {"also"}
    assert len(built) == 2


class Pipeline(TrameComponent):
    @mcp.method(annotations={"destructiveHint": True})
    def clear(self) -> None:
        """Remove every
        node."""

    @mcp.method(annotations={"readOnlyHint": True, "idempotentHint": True})
    def status(self) -> str:
        return "ok"


@pytest.mark.asyncio
async def test_method_annotations_and_docstrings(server):
    pipeline = Pipeline(server)
    pipeline.mcp_expose("pipeline", read_only=True)
    described = await ok(server, "object_types", type_names=["Pipeline"])
    methods = described["types"]["Pipeline"]["methods"]
    assert list(methods) == ["clear", "status"]
    assert methods["clear"]["description"] == "Remove every node."
    assert methods["clear"]["annotations"] == {"destructiveHint": True}
    # readOnlyHint is read_only
    assert methods["status"]["read_only"] is True
    assert methods["status"]["annotations"] == {"idempotentHint": True}
    assert await ok(server, "object_call", target="pipeline", method="status") == "ok"


@pytest.mark.asyncio
async def test_mcp_describe_on_a_class_you_dont_own(server):
    class Library(TrameComponent):
        def reset(self) -> None:
            """Reset it."""

        def other(self): ...

    with pytest.raises(TypeError, match="declares nothing"):
        Library(server).mcp_expose("lib")
    Library.mcp_describe(description="From a library.", methods=["reset"])
    lib = Library(server)
    lib.mcp_expose("lib")
    value = await ok(server, "object_types", type_names=["Library"])
    assert value["types"]["Library"]["description"] == "From a library."
    assert set(value["types"]["Library"]["methods"]) == {"reset"}
    assert await ok(server, "object_call", target=lib._id, method="reset") is None


# -----------------------------------------------------------------------------
# object_get, object_update, object_call
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_and_depth(server):
    desk = Desk(server)
    desk.mcp_expose("desk")
    view = Viewport(server)
    desk.views.append(view)  # reached through desk.active
    value = await ok(server, "object_get", target=desk._id)
    # Not read: a reference with its type
    assert read(value)["values"] == {"active": {"id": view._id, "type": "Viewport"}}
    assert list(value["objects"]) == [desk._id]
    value = await ok(server, "object_get", target=desk._id, depth=2)
    # Read: a reference by id, the object in "objects"
    assert read(value)["values"] == {"active": {"id": view._id}}
    assert value["objects"][view._id]["values"]["background"] == "black"
    value = await ok(server, "object_get", target=view._id, properties=["size"])
    assert read(value)["values"] == {"size": 300}
    message = await fails(server, "object_get", target=view._id, properties=["nope"])
    assert "has no properties ['nope']" in message


@pytest.mark.asyncio
async def test_update(server):
    view = Viewport(server)
    view.mcp_expose("view")
    assert await ok(
        server, "object_update", target=view._id, values={"background": "white"}
    ) == {"id": view._id, "updated": ["background"]}
    assert view.background == "white"

    message = await fails(
        server, "object_update", target=view._id, values={"size": 3, "nope": 1}
    )
    assert message.startswith("Nothing was applied.")
    assert "size (read-only)" in message
    assert "nope (unknown)" in message
    # Methods may change what can't be written
    assert message.endswith(
        "Writable: background. Methods: set_view_up, describe_view, wait, echo; "
        'object_types(["Viewport"]) says what they do.'
    )
    message = await fails(server, "object_update", target=view._id, values={"nope": 1})
    assert message.endswith("Writable: background")
    message = await fails(
        server, "object_update", target=view._id, values={"background": 3}
    )
    assert message == "Nothing was applied: background: expected string, got integer"

    message = await fails(
        server, "object_update", target=view._id, values={"background": "boom"}
    )
    assert message.startswith(f"Setting Viewport {view._id}.background failed")


@pytest.mark.asyncio
async def test_call(server):
    view = Viewport(server)
    view.mcp_expose("view")
    assert (
        await ok(
            server,
            "object_call",
            target=view._id,
            method="set_view_up",
            args={"axis": "z"},
        )
        == "up z"
    )
    assert (
        await ok(
            server, "object_call", target=view._id, method="wait", args={"seconds": 2}
        )
        == "waited 2.0"
    )
    message = await fails(
        server, "object_call", target=view._id, method="set_view_up", args={"axis": "w"}
    )
    assert message == (
        'Invalid arguments for Viewport.set_view_up: args.axis: must be one of "x", '
        '"y", "z", got "w"'
    )
    # A union keeps the value's own type: an int for float | int
    for given, shown in ((20, "int 20"), (2.5, "float 2.5"), ("a", "str a")):
        assert (
            await ok(
                server,
                "object_call",
                target=view._id,
                method="echo",
                args={"value": given},
            )
            == shown
        )
    message = await fails(server, "object_call", target=view._id, method="nope")
    assert message == (
        f'{view._id} (type Viewport) has no method "nope"; '
        'object_types(["Viewport"]) lists its methods.'
    )


@pytest.mark.asyncio
async def test_call_with_object_arguments(server):
    desk = Desk(server)
    desk.mcp_expose("desk")
    first, second = Viewport(server), Viewport(server)
    second.mcp_expose("second")
    desk.views.extend([first, second])

    value = await ok(
        server, "object_call", target=desk._id, method="pick", args={"view": "second"}
    )
    value = read(value)
    assert value["id"] == second._id
    assert value["names"] == ["second"]
    assert desk.active is second

    message = await fails(
        server, "object_call", target=desk._id, method="pick", args={"view": desk._id}
    )
    assert message == f'args.view: "{desk._id}" has type Desk, not Viewport'
    message = await fails(
        server, "object_call", target=desk._id, method="pick", args={"view": "999"}
    )
    assert "is not the id or name of an object agents can reach" in message


@pytest.mark.asyncio
async def test_first_class_tool_with_object_parameter(server):
    right = Viewport(server, "white")
    right.mcp_expose("right")

    @server.mcp.tool
    def screenshot(viewer: Viewport) -> str:
        """A picture of a viewer."""
        return f"picture of {viewer.background}"

    assert await ok(server, "screenshot", viewer="right") == "picture of white"

    @server.mcp.tool
    def viewers() -> dict:
        """The viewers."""
        return {"right": right, "count": 1}

    @server.mcp.tool
    def first_viewer() -> Viewport:
        """The first viewer."""
        return right

    value = await ok(server, "viewers")
    assert value["result"] == {"right": {"id": right._id}, "count": 1}
    assert value["objects"][right._id]["values"]["background"] == "white"
    value = read(await ok(server, "first_viewer"))
    assert value["values"]["background"] == "white"
    assert value["names"] == ["right"]
    tools = await server.mcp.protocol.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    schema = next(
        t["inputSchema"] for t in tools["result"]["tools"] if t["name"] == "screenshot"
    )
    # Clients read a plain string with what it names
    assert schema["properties"]["viewer"] == {
        "type": "string",
        "description": "Viewport object, by id or name",
    }


@pytest.mark.asyncio
async def test_a_concurrent_method_runs_while_a_call_holds_the_lock(server):
    release = asyncio.Event()
    log = []

    class Worker(TrameComponent):
        @mcp.method
        async def hold(self) -> str:
            log.append("hold:start")
            await release.wait()
            log.append("hold:end")
            return "held"

        @mcp.method(read_only=True, concurrent=True)
        async def peek(self) -> str:
            log.append("peek")
            return "peeked"

    worker = Worker(server)
    worker.mcp_expose("worker")
    client = server.mcp.client()

    def calling(method):
        return client.call_tool("object_call", {"target": "worker", "method": method})

    holding = asyncio.ensure_future(calling("hold"))
    await asyncio.sleep(0)  # hold takes the lock
    result = await asyncio.wait_for(calling("peek"), 1)
    assert result["content"][0]["text"] == "peeked"
    release.set()
    await holding
    assert log == ["hold:start", "peek", "hold:end"]


# -----------------------------------------------------------------------------
# Permissions
# -----------------------------------------------------------------------------


class Secret(TrameComponent):
    def __init__(self, server):
        super().__init__(server)
        self._path = "/a"

    @mcp.method(requires="files")
    def load(self, path: str) -> str:
        return path

    @mcp.property(requires="files")
    def path(self) -> str:
        return self._path

    @mcp.property
    def script(self) -> str:
        return "print()"

    @script.setter(requires="scripts")
    def script(self, value): ...


@pytest.mark.asyncio
async def test_permissions(server):
    permissions = server.mcp.permissions
    permissions.declare("files", "Read files on this computer")
    permissions.declare("scripts", "Run Python code the agent writes", requires="files")
    secret = Secret(server)
    secret.mcp_expose("secret")

    full = (await ok(server, "object_types", type_names=["Secret"]))["types"]["Secret"]
    assert full["methods"]["load"]["requires"] == ["files"]
    assert full["properties"]["path"]["requires"] == ["files"]
    assert full["properties"]["script"]["requires"] == ["scripts"]

    permissions["scripts"] = False
    full = (await ok(server, "object_types", type_names=["Secret"]))["types"]["Secret"]
    assert full["properties"]["script"] == {"type": "string", "read_only": True}
    message = await fails(
        server, "object_update", target=secret._id, values={"script": "x"}
    )
    assert "script (read-only: permission scripts is off)" in message

    permissions["files"] = False
    full = (await ok(server, "object_types", type_names=["Secret"]))["types"]["Secret"]
    assert "load" not in full["methods"]
    assert "path" not in full["properties"]
    value = read(await ok(server, "object_get", target=secret._id))
    assert value["values"] == {"script": "print()"}
    message = await fails(
        server, "object_call", target=secret._id, method="load", args={"path": "/"}
    )
    assert message == (
        'Secret.load: permission "files" (Read files on this computer) is off; only '
        "the people running the app can turn it on."
    )
    assert "files (Read files on this computer)" in server.mcp._agent_instructions()


# -----------------------------------------------------------------------------
# The state object
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state(server):
    state = server.state
    state.resolution = 6
    state.color = "red"
    state.ready()
    seen = []

    @state.change("resolution")
    def on_resolution(resolution, **_):
        seen.append(resolution)

    state.mcp_expose(
        "resolution",
        type=int,
        schema={"minimum": 3, "maximum": 60},
        description="Facets of the cone",
    )
    state.mcp_expose("color", read_only=True)

    assert await ok(server, "object_list") == {"objects": {"state": {"type": "State"}}}
    index = await ok(server, "object_types")
    assert index["types"]["State"] == {"properties": ["resolution", "color"]}
    full = await ok(server, "object_types", type_names=["State"])
    assert full["types"]["State"]["properties"] == {
        "resolution": {
            "type": "integer",
            "minimum": 3,
            "maximum": 60,
            "description": "Facets of the cone",
        },
        "color": {"read_only": True},
    }

    assert await ok(server, "object_get", target="state") == {
        "result": {"id": "state"},
        "objects": {
            "state": {"type": "State", "values": {"resolution": 6, "color": "red"}}
        },
    }
    assert await ok(
        server, "object_update", target="state", values={"resolution": 24}
    ) == {"id": "state", "updated": ["resolution"]}
    assert state.resolution == 24
    assert seen == [24]

    message = await fails(
        server, "object_update", target="state", values={"resolution": 2, "color": "b"}
    )
    assert "color (read-only)" in message
    message = await fails(
        server, "object_update", target="state", values={"resolution": 2}
    )
    assert message == "Nothing was applied: resolution: must be at least 3, got 2"
    assert state.resolution == 24

    state.mcp_unexpose("resolution", "color")
    assert "Unknown object" in await fails(server, "object_get", target="state")


@pytest.mark.asyncio
async def test_state_of_child_servers(server):
    child = server.create_child_server(prefix="left_")
    child.state.background = "black"
    child.state.mcp_expose("background", type=str)
    value = read(await ok(server, "object_get", target="state"))
    assert value["values"] == {"left_background": "black"}
    await ok(server, "object_update", target="state", values={"left_background": "w"})
    assert child.state.background == "w"


@pytest.mark.asyncio
async def test_child_servers_translate_names(server):
    """As they do state keys: a component built on each child server exposes
    each instance under its own name."""
    left = server.create_child_server(prefix="left_")
    right = server.create_child_server(prefix="right_")
    left_view, right_view = Viewport(left), Viewport(right)
    left_view.mcp_expose("viewer")
    right_view.mcp_expose("viewer")
    left.mcp.expose_object(lambda: left_view, "active")

    assert (await ok(server, "object_list"))["objects"] == {
        "left_viewer": {"type": "Viewport"},
        "right_viewer": {"type": "Viewport"},
        "left_active": {"type": "Viewport"},
    }
    assert read(await ok(server, "object_get", target="right_viewer"))["id"] == (
        right_view._id
    )
    with pytest.raises(ValueError, match="'left_viewer' already exposes"):
        left.mcp.expose_object(right_view, "viewer")

    left.mcp.unexpose_object("active")
    assert "left_active" not in (await ok(server, "object_list"))["objects"]


def test_context_cannot_be_exposed(server):
    with pytest.raises(RuntimeError, match="server-only"):
        server.context.mcp_expose("secret")


# -----------------------------------------------------------------------------
# object_batch
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch(server):
    desk = Desk(server)
    view = Viewport(server)
    desk.views.append(view)
    desk.mcp_expose("desk")
    server.state.mcp_expose("zoom", type=float)

    value = await ok(
        server,
        "object_batch",
        steps=[
            {"call": "desk", "method": "pick", "args": {"view": view._id}, "as": "v"},
            {"update": "@v", "values": {"background": "white"}},
            {"call": "@v", "method": "set_view_up", "args": {"axis": "x"}},
            {"update": "state", "values": {"zoom": 2}},
        ],
    )
    assert value == {
        "results": [
            {"id": view._id},
            {"id": view._id, "updated": ["background"]},
            "up x",
            {"id": "state", "updated": ["zoom"]},
        ],
        "objects": {view._id: {"type": "Viewport"}},  # links only, and none
    }
    value = await ok(
        server,
        "object_batch",
        steps=[{"call": "desk", "method": "pick", "args": {"view": view._id}}],
        results="full",
    )
    assert value["objects"][view._id]["values"]["background"] == "white"
    assert view.background == "white"
    assert server.state.zoom == 2.0

    message = await fails(
        server,
        "object_batch",
        steps=[
            {"call": "desk", "method": "pick", "args": {"view": view._id}},
            {"update": view._id, "values": {"background": "boom"}},
        ],
    )
    assert message.startswith(
        f"steps[1] (update {view._id}) failed: Setting Viewport {view._id}.background"
    )
    assert ". Step 0 stays applied (no rollback); its result: " in message
    assert ".." not in message
    # The first step: its own error, alone
    message = await fails(
        server,
        "object_batch",
        steps=[{"update": view._id, "values": {"size": 3}}],
    )
    assert message == (
        f"steps[0] (update {view._id}) failed: Nothing was applied. Rejected on "
        f"Viewport {view._id}: size (read-only). Writable: background. Methods: "
        f'set_view_up, describe_view, wait, echo; object_types(["Viewport"]) '
        f"says what they do."
    )

    message = await fails(server, "object_batch", steps=[{"new": "Viewport"}])
    assert 'no type "Viewport" can be built' in message
    message = await fails(
        server, "object_batch", steps=[{"update": "@x", "values": {}}]
    )
    assert "names no earlier step" in message


class Tile(TrameComponent, mcp={"constructor": "default"}):
    """A tile on the wall."""

    @mcp.property
    def label(self) -> str:
        return getattr(self, "_label", "")

    @label.setter
    def label(self, value: str):
        self._label = value


class Poster(TrameComponent):
    """A poster on the wall."""

    @mcp.constructor
    @classmethod
    def hang(cls, server, title: str) -> "Poster":
        """Hang a new poster."""
        poster = cls(server)
        poster.title = title
        return poster

    @mcp.method(read_only=True)
    def caption(self) -> str:
        return self.title


class Wall(TrameComponent):
    def __init__(self, server):
        super().__init__(server)
        self._tiles = []
        self._posters = []

    # Agents create the types they can reach, here through these properties
    @mcp.property
    def tiles(self) -> list[Tile]:
        return list(self._tiles)

    @mcp.property
    def posters(self) -> list[Poster]:
        return list(self._posters)

    @mcp.method
    def add(self, tile: Tile) -> int:
        self._tiles.append(tile)
        return len(self._tiles)


@pytest.mark.asyncio
async def test_agents_create_components(server):
    wall = Wall(server)
    wall.mcp_expose("wall")

    types = (await ok(server, "object_types", type_names=["Tile", "Poster"]))["types"]
    tile_new, poster_new = types["Tile"]["constructor"], types["Poster"]["constructor"]
    assert tile_new["parameters"]["properties"] == {}  # Tile(server)
    assert poster_new["description"] == "Hang a new poster."
    assert list(poster_new["parameters"]["properties"]) == ["title"]

    value = await ok(
        server,
        "object_batch",
        steps=[
            {"new": "Tile", "as": "t"},
            {"update": "@t", "values": {"label": "north"}},
            {"call": "wall", "method": "add", "args": {"tile": "@t"}},
            {"new": "Poster", "args": {"title": "Hello"}, "as": "p"},
            {"call": "@p", "method": "caption"},
        ],
    )
    results = value["results"]
    assert results[2] == 1
    assert results[4] == "Hello"
    (tile,) = wall._tiles
    assert isinstance(tile, Tile)
    assert tile.server is server
    assert tile.label == "north"
    assert results[0] == {"id": tile._id}


# -----------------------------------------------------------------------------
# Response budget and instructions
# -----------------------------------------------------------------------------


class Gauge(TrameComponent):
    def __init__(self, server, count):
        super().__init__(server)
        self.count = count

    @mcp.property
    def samples(self) -> list[int]:
        return list(range(self.count))

    @mcp.property
    def label(self) -> str:
        return "x" * 1000


@pytest.mark.asyncio
async def test_unrequested_values_are_capped(server):
    gauge = Gauge(server, 240)
    gauge.mcp_expose("gauge")
    value = await ok(server, "object_get", target="gauge")
    assert read(value)["values"]["samples"] == list(range(20))
    assert len(read(value)["values"]["label"]) == 400
    assert value["more"] == {
        f"{gauge._id}.samples": '20 of 240 items shown; object_get("gauge", '
        'properties=["samples"]) for all',
        f"{gauge._id}.label": '400 of 1000 characters shown; object_get("gauge", '
        'properties=["label"]) for all',
    }
    value = await ok(server, "object_get", target="gauge", properties=["samples"])
    assert read(value)["values"]["samples"] == list(range(240))
    assert "more" not in value


@pytest.mark.asyncio
async def test_replies_fit_the_budget(server):
    server.mcp.max_response_tokens = 500  # 2000 characters
    gauge = Gauge(server, 5000)
    gauge.mcp_expose("gauge")
    value = await ok(
        server, "object_get", target=gauge._id, properties=["samples", "label"]
    )
    assert len(json.dumps(value)) <= 2000
    assert "to fit the response budget" in value["more"][f"{gauge._id}.samples"]
    with pytest.raises(ValueError, match="at least 500"):
        server.mcp.max_response_tokens = 10


class Ledger(TrameComponent):
    @mcp.property
    def entries(self) -> list[str]:
        return ["y" * 300] * 30


@pytest.mark.asyncio
async def test_cut_values_count_from_what_was_read(server):
    server.mcp.max_response_tokens = 500
    ledger = Ledger(server)
    ledger.mcp_expose("ledger")
    value = await ok(server, "object_get", target=ledger._id)
    # Capped to 20 items, then cut again to fit: the note counts the 30
    shown = len(read(value)["values"]["entries"])
    assert shown < 20
    assert value["more"][f"{ledger._id}.entries"] == (
        f'{shown} of 30 items shown; object_get("{ledger._id}", '
        f'properties=["entries"]) alone for more'
    )


@pytest.mark.asyncio
async def test_instructions(server):
    views = [Viewport(server) for _ in range(25)]  # names hold them weakly
    for i, view in enumerate(views):
        view.mcp_expose(f"view_{i}")
    response = await server.mcp.protocol.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    text = response["result"]["instructions"]
    lines = text.split("\n")
    assert lines[0] == (
        "A live trame app, shared with its users: they see your changes at once."
    )
    assert lines[1].startswith("Objects: view_0 (Viewport), view_1 (Viewport)")
    assert lines[1].endswith(
        ", and 5 more; object_list() lists them, object_types() describes their types."
    )
    assert len(text) < 1000


@pytest.mark.asyncio
async def test_object_list_pages(server):
    server.mcp.max_response_tokens = 500  # 2000 characters
    views = [Viewport(server) for _ in range(60)]  # names hold them weakly
    for i, view in enumerate(views):
        view.mcp_expose(f"view_{i}", description="One of many views.")
    page = await ok(server, "object_list")
    assert len(json.dumps(page, separators=(",", ":"))) <= 2000
    shown = len(page["objects"])
    assert 1 < shown < 60
    assert page["more"] == {
        "objects": (
            f"1-{shown} of 60 listed to fit the response budget; "
            f"object_list(offset={shown}) lists the next ones"
        )
    }

    listed = dict(page["objects"])
    while "more" in page:
        page = await ok(server, "object_list", offset=len(listed))
        listed.update(page["objects"])
    assert list(listed) == [f"view_{i}" for i in range(60)]
    assert await ok(server, "object_list", offset=60) == {"objects": {}}


# -----------------------------------------------------------------------------
# First-class tools of a component built once
# -----------------------------------------------------------------------------


class Console(TrameComponent):
    """Only first-class tools: not an object."""

    @mcp.tool(read_only=True)
    def status(self) -> dict:
        """How the app is doing."""
        return {"ok": True}

    @mcp.resource("app://guide", mime_type="text/markdown")
    def guide(self) -> str:
        """How to use the app."""
        return "# Guide"

    @mcp.prompt
    def review(self, focus: str = "all") -> str:
        """Review the session."""
        return f"Review {focus}"


class Studio(TrameComponent):
    @mcp.method
    @mcp.tool(name="studio_reset")
    def reset(self) -> str:
        """Back to defaults."""
        return "reset"


async def rpc(server, method, **params):
    response = await server.mcp.protocol.handle(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    return response["result"]


@pytest.mark.asyncio
async def test_first_class_markers(server):
    console = Console(server)
    tools = (await rpc(server, "tools/list"))["tools"]
    assert [t["name"] for t in tools] == ["status"]  # not an object: no object tools
    assert tools[0]["annotations"] == {"readOnlyHint": True}
    assert await ok(server, "status") == {"ok": True}
    resources = (await rpc(server, "resources/list"))["resources"]
    assert resources == [
        {
            "uri": "app://guide",
            "name": "guide",
            "description": "How to use the app.",
            "mimeType": "text/markdown",
        }
    ]
    read = await rpc(server, "resources/read", uri="app://guide")
    assert read["contents"][0]["text"] == "# Guide"
    prompt = await rpc(server, "prompts/get", name="review", arguments={"focus": "x"})
    assert prompt["messages"][0]["content"]["text"] == "Review x"

    # Built once: a second one would take the same names
    with pytest.raises(ValueError, match="for components built once"):
        Console(server)
    assert server.mcp._tools["status"].fn.__self__ is console

    # Unbinding removes them, so another can be built
    console._unbind_annotated_methods()
    assert "status" not in server.mcp._tools
    assert not server.mcp._resources
    assert not server.mcp._prompts
    second = Console(server)
    assert server.mcp._tools["status"].fn.__self__ is second


@pytest.mark.asyncio
async def test_a_method_can_be_both(server):
    studio = Studio(server)
    assert await ok(server, "studio_reset") == "reset"  # a tool needs no name
    studio.mcp_expose("studio")
    assert await ok(server, "object_call", target=studio._id, method="reset") == "reset"


@pytest.mark.asyncio
async def test_object_values_are_ids(server):
    desk = Desk(server)
    desk.mcp_expose("desk")
    message = await fails(
        server,
        "object_call",
        target=desk._id,
        method="pick",
        args={"view": {"id": "3"}},
    )
    assert message == (
        "Invalid arguments for Desk.pick: args.view: expected the id of an object "
        "of type Viewport, got object"
    )
