"""MCP JSON-RPC dispatch (``mcp.protocol``), without HTTP."""

import asyncio
import base64
import itertools
import json
from typing import Annotated, Literal

import pytest
from trame.app import get_server

from trame_server import __version__
from trame_server.mcp import Image, MCPDisabledError, ToolError
from trame_server.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LEGACY_VERSIONS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSIONS,
    REQUEST_CANCELLED,
    UNSUPPORTED_VERSION,
)

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)

_counter = itertools.count()


def rpc(method, params=None, rpc_id=1):
    msg = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def modern(method, params=None, rpc_id=1, version="2026-07-28", capabilities=None):
    """A request as clients of 2026-07-28 send it: its version and the
    client's capabilities in _meta."""
    meta = {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": capabilities or {},
    }
    return rpc(method, {**(params or {}), "_meta": meta}, rpc_id=rpc_id)


def call_tool(mcp, name, rpc_id=1, **arguments):
    return mcp.protocol.handle(
        rpc("tools/call", {"name": name, "arguments": arguments}, rpc_id=rpc_id)
    )


def text_of(response):
    return response["result"]["content"][0]["text"]


def cancel_notification(request_id, reason=None):
    params = {"requestId": request_id}
    if reason is not None:
        params["reason"] = reason
    return {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": params}


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mcp():
    mcp = get_server(f"test_mcp_protocol_{next(_counter)}").mcp
    mcp.enabled = True
    return mcp


@pytest.fixture
def protocol(mcp):
    @mcp.tool
    def add(a: int, b: int = 1) -> int:
        """Add two numbers."""
        return a + b

    @mcp.tool
    async def async_echo(text: str) -> str:
        return text

    @mcp.tool
    def failing():
        msg = "boom"
        raise RuntimeError(msg)

    @mcp.resource("trame://info", mime_type="application/json")
    def info():
        return {"name": "test"}

    @mcp.prompt
    def walkthrough(topic: Annotated[str, "Part of the app to explain"] = "app") -> str:
        return f"Explain the {topic}"

    return mcp.protocol


# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize(protocol, mcp):
    response = await protocol.handle(rpc("initialize", {"capabilities": {}}))
    result = response["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert set(result["capabilities"]) == {"tools", "resources", "prompts"}
    assert result["serverInfo"] == {"name": mcp.server.name, "version": __version__}

    mcp.name = "viewer"
    response = await protocol.handle(rpc("initialize"))
    assert response["result"]["serverInfo"]["name"] == "viewer"


def test_protocol_versions():
    assert PROTOCOL_VERSIONS == (
        "2026-07-28",
        "2025-11-25",
        "2025-06-18",
        "2025-03-26",
        "2024-11-05",
    )
    assert LEGACY_VERSIONS == PROTOCOL_VERSIONS[1:]  # those opening with initialize


@pytest.mark.asyncio
@pytest.mark.parametrize("version", LEGACY_VERSIONS)
async def test_initialize_negotiates_older_versions(protocol, version):
    response = await protocol.handle(rpc("initialize", {"protocolVersion": version}))
    assert response["result"]["protocolVersion"] == version


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "version",
    # 2026-07-28 has no handshake: initialize can't select it
    ["1999-01-01", None, ["2025-06-18"], "2026-07-28"],
)
async def test_initialize_unknown_version_falls_back(protocol, version):
    response = await protocol.handle(rpc("initialize", {"protocolVersion": version}))
    assert response["result"]["protocolVersion"] == "2025-11-25"


@pytest.mark.asyncio
async def test_initialize_sends_app_then_generated_instructions(mcp):
    async def instructions():
        response = await mcp.protocol.handle(rpc("initialize"))
        return response["result"]["instructions"]

    # nothing exposed: only the live-app notice
    text = await instructions()
    assert (
        text
        == "A live trame app, shared with its users: they see your changes at once."
    )

    mcp.instructions = "A library catalog.\n"
    mcp.server.state.query = ""
    mcp.server.state.mcp_expose("query", read_only=True)
    lines = (await instructions()).split("\n")
    assert lines[0] == "A library catalog."
    assert lines[1] == ""
    assert lines[2].startswith("A live trame app")
    assert lines[3] == (
        "Objects: state (State); object_list() lists them, object_types() "
        "describes their types."
    )


# -----------------------------------------------------------------------------
# 2026-07-28: no handshake, every request names its version
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover(protocol, mcp):
    mcp.instructions = "A test app."
    response = await protocol.handle(modern("server/discover"))
    result = response["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == list(PROTOCOL_VERSIONS)
    assert set(result["capabilities"]) == {"tools", "resources", "prompts"}
    assert result["instructions"].startswith("A test app.")
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": mcp.server.name,
        "version": __version__,
    }
    assert (result["ttlMs"], result["cacheScope"]) == (0, "private")


@pytest.mark.asyncio
async def test_modern_results(protocol, mcp):
    """Every result says it is complete and who answered; lists and reads
    also carry caching hints: none fresh, none shared."""
    server_info = {"name": mcp.server.name, "version": __version__}
    listed = (await protocol.handle(modern("tools/list")))["result"]
    assert listed["resultType"] == "complete"
    assert listed["_meta"] == {"io.modelcontextprotocol/serverInfo": server_info}
    assert (listed["ttlMs"], listed["cacheScope"]) == (0, "private")
    assert "add" in [tool["name"] for tool in listed["tools"]]

    called = await protocol.handle(
        modern("tools/call", {"name": "add", "arguments": {"a": 2}})
    )
    result = called["result"]
    assert result["content"] == [{"type": "text", "text": "3"}]
    assert result["resultType"] == "complete"
    assert result["_meta"] == {"io.modelcontextprotocol/serverInfo": server_info}
    assert "ttlMs" not in result

    # A tool's failure is a complete result too
    failed = await protocol.handle(modern("tools/call", {"name": "failing"}))
    assert failed["result"]["isError"] is True
    assert failed["result"]["resultType"] == "complete"

    # Clients before 2026-07-28 get the results of their revision
    legacy = (await protocol.handle(rpc("tools/list")))["result"]
    assert not {"resultType", "ttlMs", "cacheScope", "_meta"} & set(legacy)


@pytest.mark.asyncio
async def test_an_unsupported_version(protocol):
    response = await protocol.handle(modern("tools/list", version="1900-01-01"))
    error = response["error"]
    assert error["code"] == UNSUPPORTED_VERSION
    assert error["data"] == {
        "supported": list(PROTOCOL_VERSIONS),
        "requested": "1900-01-01",
    }

    # an earlier revision isn't spoken this way: it opens with initialize
    response = await protocol.handle(modern("tools/list", version="2025-11-25"))
    assert response["error"]["code"] == UNSUPPORTED_VERSION
    assert "it opens with initialize" in response["error"]["message"]


@pytest.mark.asyncio
async def test_the_client_capabilities_are_required(protocol):
    message = modern("tools/list")
    del message["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    response = await protocol.handle(message)
    assert response["error"]["code"] == INVALID_PARAMS
    assert "clientCapabilities" in response["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["initialize", "ping"])
async def test_the_handshake_and_ping_are_gone(protocol, method):
    response = await protocol.handle(modern(method))
    assert response["error"]["code"] == METHOD_NOT_FOUND
    assert protocol.handles(modern(method)) is False
    assert protocol.handles(rpc(method)) is True  # still served to older clients
    assert protocol.handles(rpc("server/discover")) is False


@pytest.mark.asyncio
async def test_notifications_and_client_responses_get_no_response(protocol):
    assert await protocol.handle(rpc("notifications/initialized", rpc_id=None)) is None
    msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert await protocol.handle(msg) is None
    # a reply to a request of the server's
    assert await protocol.handle({"jsonrpc": "2.0", "id": 5, "result": {}}) is None


@pytest.mark.asyncio
async def test_malformed_requests(protocol):
    for message in ({"id": 1, "method": "ping"}, {"jsonrpc": "1.0"}, [rpc("ping")]):
        response = await protocol.handle(message)
        assert response["id"] is None
        assert response["error"]["code"] == INVALID_REQUEST
    response = await protocol.handle(rpc("tools/list", params=["not", "a", "dict"]))
    assert response["error"]["code"] == INVALID_PARAMS
    response = await protocol.handle({"jsonrpc": "2.0", "id": 1, "method": 42})
    assert response["error"]["code"] == INVALID_REQUEST
    response = await protocol.handle(
        rpc("prompts/get", {"name": "walkthrough", "arguments": {"bogus": "x"}})
    )
    assert response["error"]["code"] == INVALID_PARAMS


@pytest.mark.asyncio
async def test_unknown_method(protocol):
    response = await protocol.handle(rpc("bogus/method", rpc_id="a"))
    assert response == {
        "jsonrpc": "2.0",
        "id": "a",
        "error": {
            "code": METHOD_NOT_FOUND,
            "message": "Method not found: bogus/method",
        },
    }


@pytest.mark.asyncio
async def test_ping(protocol):
    response = await protocol.handle(rpc("ping"))
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {}}


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list(protocol, mcp):
    @mcp.tool(read_only=True)
    def peek() -> str:
        return "ok"

    @mcp.tool(read_only=True, annotations={"openWorldHint": False})
    def look() -> str:
        return "ok"

    response = await protocol.handle(rpc("tools/list"))
    tools = {t["name"]: t for t in response["result"]["tools"]}
    assert list(tools) == ["add", "async_echo", "failing", "peek", "look"]
    assert tools["add"]["description"] == "Add two numbers."
    assert tools["add"]["inputSchema"] == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer", "default": 1},
        },
        "required": ["a"],
        "additionalProperties": False,
    }
    assert "annotations" not in tools["add"]
    assert tools["failing"]["description"] == ""
    assert tools["peek"]["annotations"] == {"readOnlyHint": True}
    assert tools["look"]["annotations"] == {
        "openWorldHint": False,
        "readOnlyHint": True,
    }


@pytest.mark.asyncio
async def test_the_object_tools_are_listed_once_something_is_exposed(mcp):
    response = await mcp.protocol.handle(rpc("tools/list"))
    assert response["result"]["tools"] == []

    mcp.server.state.size = 1
    mcp.server.state.mcp_expose("size", type=int)
    response = await mcp.protocol.handle(rpc("tools/list"))
    assert [t["name"] for t in response["result"]["tools"]] == [
        "object_list",
        "object_types",
        "object_get",
        "object_update",
        "object_call",
        "object_batch",
    ]


@pytest.mark.asyncio
async def test_tools_call_sync_and_async(protocol):
    response = await protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})
    )
    assert response["result"] == {"content": [{"type": "text", "text": "5"}]}

    response = await protocol.handle(
        rpc("tools/call", {"name": "async_echo", "arguments": {"text": "hi"}})
    )
    assert response["result"]["content"] == [{"type": "text", "text": "hi"}]


@pytest.mark.asyncio
async def test_tools_call_without_arguments(mcp):
    @mcp.tool
    def hello() -> str:
        return "hi"

    response = await mcp.protocol.handle(rpc("tools/call", {"name": "hello"}))
    assert text_of(response) == "hi"


@pytest.mark.asyncio
async def test_tools_call_errors_go_in_the_result(protocol, mcp):
    @mcp.tool
    def refuse(reason: str):
        if reason == "tool":
            msg = "Pick a smaller value; object_get shows the range."
            raise ToolError(msg)
        if reason == "value":
            msg = "bad value"
            raise ValueError(msg)
        msg = "not yours"
        raise PermissionError(msg)

    response = await protocol.handle(rpc("tools/call", {"name": "failing"}))
    assert response["result"] == {
        "content": [{"type": "text", "text": "RuntimeError: boom"}],
        "isError": True,
    }
    # complete messages are sent as they are
    response = await call_tool(mcp, "refuse", reason="tool")
    assert text_of(response) == "Pick a smaller value; object_get shows the range."
    response = await call_tool(mcp, "refuse", reason="permission")
    assert text_of(response) == "not yours"
    response = await call_tool(mcp, "refuse", reason="value")
    assert text_of(response) == "ValueError: bad value"


@pytest.mark.asyncio
async def test_tools_call_bad_arguments(protocol, mcp):
    @mcp.tool
    def set_view_up(axis: Literal["x", "y", "z"]) -> str:
        return axis

    async def call(name, arguments):
        response = await protocol.handle(
            rpc("tools/call", {"name": name, "arguments": arguments})
        )
        result = response["result"]
        assert result["isError"] is True
        return result["content"][0]["text"]

    assert "unexpected 'wrong'" in await call("add", {"a": 1, "wrong": 1})
    assert "missing required 'a'" in await call("add", {})
    assert await call("add", {"a": "1"}) == (
        "Invalid arguments for tool add: arguments.a: expected integer, got string"
    )
    assert await call("add", [1]) == (
        "Invalid arguments for tool add: arguments: expected object, got array"
    )
    assert await call("set_view_up", {"axis": "w"}) == (
        "Invalid arguments for tool set_view_up: arguments.axis: must be one of "
        '"x", "y", "z", got "w"'
    )


@pytest.mark.asyncio
async def test_tools_call_type_error_in_body_is_not_blamed_on_arguments(mcp):
    @mcp.tool
    def measure(x: int) -> int:
        return len(x)

    text = text_of(await call_tool(mcp, "measure", x=3))
    assert text.startswith("TypeError:")
    assert "Invalid arguments" not in text


@pytest.mark.asyncio
async def test_tools_call_coerces_lossless_numbers(mcp):
    @mcp.tool
    def numbers(i: int, f: float) -> dict:
        return {"i": type(i).__name__, "f": type(f).__name__}

    response = await call_tool(mcp, "numbers", i=2.0, f=2)
    assert json.loads(text_of(response)) == {"i": "int", "f": "float"}


@pytest.mark.asyncio
async def test_tools_call_restores_declared_tuples(mcp):
    @mcp.tool
    def place(position: tuple[float, float, float]) -> str:
        return type(position).__name__ + repr(position)

    response = await call_tool(mcp, "place", position=[1, 2, 3])
    assert text_of(response) == "tuple(1.0, 2.0, 3.0)"


@pytest.mark.asyncio
async def test_a_result_is_sent_once_unless_asked_twice(mcp):
    @mcp.tool
    def info() -> dict:
        return {"name": "Å", "sizes": [1, 2]}

    response = await mcp.protocol.handle(rpc("tools/call", {"name": "info"}))
    assert response["result"] == {
        "content": [{"type": "text", "text": '{"name":"Å","sizes":[1,2]}'}]
    }
    mcp.structured_content = True
    response = await mcp.protocol.handle(rpc("tools/call", {"name": "info"}))
    assert response["result"]["structuredContent"] == {"name": "Å", "sizes": [1, 2]}


@pytest.mark.asyncio
async def test_results_become_content(mcp):
    png = b"\x89PNG\r\n"
    encoded = base64.b64encode(png).decode()

    @mcp.tool
    def nothing() -> None:
        pass

    @mcp.tool
    def screenshot() -> Image:
        return Image(png)

    @mcp.tool
    def views() -> list:
        return [Image(png, mime_type="image/jpeg"), "front"]

    @mcp.tool
    def numbers() -> list:
        return [1, 2.5, None]

    @mcp.tool
    def mixed() -> dict:
        return {"image": Image(png), "tags": {1}}

    async def result(name):
        return (await call_tool(mcp, name))["result"]

    assert await result("nothing") == {"content": [{"type": "text", "text": "null"}]}
    assert await result("screenshot") == {
        "content": [{"type": "image", "data": encoded, "mimeType": "image/png"}]
    }
    assert await result("views") == {
        "content": [
            {"type": "image", "data": encoded, "mimeType": "image/jpeg"},
            {"type": "text", "text": "front"},
        ]
    }
    assert await result("numbers") == {
        "content": [{"type": "text", "text": "[1,2.5,null]"}]
    }
    assert (await result("mixed"))["content"][0]["text"] == (
        '{"image":"<image image/png>","tags":"{1}"}'
    )


@pytest.mark.asyncio
async def test_tools_call_unknown_tool(protocol):
    response = await protocol.handle(rpc("tools/call", {"name": "nope"}))
    assert response["error"] == {
        "code": INVALID_PARAMS,
        "message": "Unknown tool: nope",
    }


@pytest.mark.asyncio
async def test_a_bound_method_is_a_tool(mcp):
    class ProtoCounter:
        def __init__(self):
            self.count = 0

        def increment(self, by: Annotated[int, "Step", {"minimum": 1}] = 1) -> int:
            """Count up."""
            self.count += by
            return self.count

    counter = ProtoCounter()
    assert mcp.tool(counter.increment) == counter.increment
    entry = mcp.get_tool("increment")
    assert entry.description == "Count up."
    response = await mcp.protocol.handle(rpc("tools/list"))
    (descriptor,) = response["result"]["tools"]
    assert descriptor["inputSchema"]["properties"] == {
        "by": {"type": "integer", "description": "Step", "minimum": 1, "default": 1}
    }
    assert text_of(await call_tool(mcp, "increment", by=2)) == "2"
    assert counter.count == 2
    assert "must be at least 1" in text_of(await call_tool(mcp, "increment", by=0))


@pytest.mark.asyncio
async def test_the_object_tools_are_served_like_any_tool(mcp):
    state = mcp.server.state
    state.resolution = 6
    state.ready()  # what starting the server does: flushes run from now on
    state.mcp_expose("resolution", type=int, schema={"minimum": 3})
    seen = []

    @state.change("resolution")
    def on_resolution(resolution, **_):
        seen.append(resolution)

    response = await call_tool(
        mcp, "object_update", target="state", values={"resolution": 12}
    )
    assert json.loads(text_of(response)) == {"id": "state", "updated": ["resolution"]}
    assert state.resolution == 12
    assert seen == [12]

    response = await call_tool(mcp, "object_get", target="state")
    reply = json.loads(text_of(response))
    assert reply["objects"]["state"]["values"] == {"resolution": 12}

    response = await call_tool(
        mcp, "object_update", target="state", values={"resolution": 1}
    )
    assert response["result"]["isError"] is True
    assert state.resolution == 12


# -----------------------------------------------------------------------------
# Resources and prompts
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resources(protocol, mcp):
    @mcp.resource("trame://logo", name="logo", description="The logo")
    def logo() -> bytes:
        return b"\x00\x01"

    @mcp.resource("trame://readme")
    async def readme() -> str:
        """How to use it."""
        return "# Readme"

    @mcp.resource("trame://sizes")
    def sizes() -> list:
        return [1, 2]

    response = await protocol.handle(rpc("resources/list"))
    assert response["result"]["resources"] == [
        {"uri": "trame://info", "name": "info", "mimeType": "application/json"},
        {"uri": "trame://logo", "name": "logo", "description": "The logo"},
        {"uri": "trame://readme", "name": "readme", "description": "How to use it."},
        {"uri": "trame://sizes", "name": "sizes"},
    ]

    async def read(uri):
        response = await protocol.handle(rpc("resources/read", {"uri": uri}))
        (content,) = response["result"]["contents"]
        return content

    assert await read("trame://info") == {
        "uri": "trame://info",
        "mimeType": "application/json",
        "text": '{"name": "test"}',
    }
    assert await read("trame://logo") == {
        "uri": "trame://logo",
        "mimeType": "application/octet-stream",
        "blob": base64.b64encode(b"\x00\x01").decode(),
    }
    assert await read("trame://readme") == {
        "uri": "trame://readme",
        "mimeType": "text/plain",
        "text": "# Readme",
    }
    assert (await read("trame://sizes"))["text"] == "[1, 2]"

    response = await protocol.handle(rpc("resources/read", {"uri": "trame://nope"}))
    assert response["error"]["code"] == INVALID_PARAMS


@pytest.mark.asyncio
async def test_a_failing_resource_is_an_internal_error(mcp):
    @mcp.resource("trame://broken")
    def broken():
        msg = "no data"
        raise RuntimeError(msg)

    response = await mcp.protocol.handle(
        rpc("resources/read", {"uri": "trame://broken"})
    )
    assert response["error"] == {
        "code": INTERNAL_ERROR,
        "message": "RuntimeError: no data",
    }


@pytest.mark.asyncio
async def test_resource_templates_list(protocol):
    response = await protocol.handle(rpc("resources/templates/list"))
    assert response["result"] == {"resourceTemplates": []}


@pytest.mark.asyncio
async def test_prompts(protocol, mcp):
    @mcp.prompt(name="review", description="Review the session.")
    async def review_session(focus: str) -> list:
        return [{"role": "user", "content": {"type": "text", "text": focus}}]

    response = await protocol.handle(rpc("prompts/list"))
    assert response["result"]["prompts"] == [
        {
            "name": "walkthrough",
            "arguments": [
                {
                    "name": "topic",
                    "required": False,
                    "description": "Part of the app to explain",
                }
            ],
        },
        {
            "name": "review",
            "description": "Review the session.",
            "arguments": [{"name": "focus", "required": True}],
        },
    ]

    response = await protocol.handle(
        rpc("prompts/get", {"name": "walkthrough", "arguments": {"topic": "cone"}})
    )
    assert response["result"] == {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "Explain the cone"}}
        ]
    }

    # a list of messages is sent as is
    response = await protocol.handle(
        rpc("prompts/get", {"name": "review", "arguments": {"focus": "colors"}})
    )
    assert response["result"] == {
        "description": "Review the session.",
        "messages": [{"role": "user", "content": {"type": "text", "text": "colors"}}],
    }

    response = await protocol.handle(rpc("prompts/get", {"name": "review"}))
    assert response["error"]["code"] == INVALID_PARAMS
    assert response["error"]["message"].startswith(
        "Invalid arguments for prompt review"
    )
    response = await protocol.handle(rpc("prompts/get", {"name": "nope"}))
    assert response["error"] == {
        "code": INVALID_PARAMS,
        "message": "Unknown prompt: nope",
    }


@pytest.mark.asyncio
async def test_disabled_blocks_tools_resources_and_prompts(protocol, mcp):
    mcp.enabled = False

    response = await protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 1}})
    )
    assert response["result"] == {
        "content": [
            {
                "type": "text",
                "text": "MCP access is currently disabled by the application",
            }
        ],
        "isError": True,
    }
    with pytest.raises(MCPDisabledError):
        await protocol._execute(mcp.get_tool("add"), {"a": 1})

    response = await protocol.handle(rpc("resources/read", {"uri": "trame://info"}))
    assert response["error"]["code"] == INVALID_REQUEST
    assert "disabled" in response["error"]["message"]
    response = await protocol.handle(rpc("prompts/get", {"name": "walkthrough"}))
    assert "disabled" in response["error"]["message"]

    mcp.enabled = True
    assert await protocol._execute(mcp.get_tool("add"), {"a": 1}) == 2


# -----------------------------------------------------------------------------
# Running calls
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_async_tool_calls_run_one_at_a_time(mcp):
    log = []

    @mcp.tool
    async def slow(tag: str) -> str:
        log.append(f"start:{tag}")
        await asyncio.sleep(0.01)
        log.append(f"end:{tag}")
        return tag

    await asyncio.gather(
        call_tool(mcp, "slow", tag="a"), call_tool(mcp, "slow", tag="b")
    )

    # One at a time, each start is immediately followed by its own end
    assert len(log) == 4
    for i in (0, 2):
        tag = log[i].split(":")[1]
        assert log[i] == f"start:{tag}"
        assert log[i + 1] == f"end:{tag}"


@pytest.mark.asyncio
async def test_concurrent_calls_overlap(mcp):
    log = []

    @mcp.tool
    async def slow(tag: str) -> str:
        log.append(f"start:{tag}")
        await asyncio.sleep(0.01)
        log.append(f"end:{tag}")
        return tag

    mcp.concurrent_calls = True
    await asyncio.gather(
        call_tool(mcp, "slow", tag="a"), call_tool(mcp, "slow", tag="b")
    )
    assert log == ["start:a", "start:b", "end:a", "end:b"]


@pytest.mark.asyncio
async def test_tool_state_changes_are_flushed(mcp):
    state = mcp.server.state
    state.resolution = 6
    state.ready()  # what starting the server does: flushes run from now on
    seen = []

    @state.change("resolution")
    def on_resolution(resolution, **_):
        seen.append(resolution)

    @mcp.tool
    def set_resolution(resolution: int) -> int:
        state.resolution = resolution  # no `with state:`
        return resolution

    @mcp.tool
    async def set_later(resolution: int) -> int:
        await asyncio.sleep(0)
        state.resolution = resolution
        return resolution

    await call_tool(mcp, "set_resolution", resolution=12)
    assert seen == [12]

    await call_tool(mcp, "set_later", resolution=18)
    assert seen == [12, 18]


@pytest.mark.asyncio
async def test_concurrent_tools_run_while_a_call_holds_the_lock(mcp):
    release = asyncio.Event()
    log = []

    @mcp.tool
    async def hold() -> str:
        log.append("hold:start")
        await release.wait()
        log.append("hold:end")
        return "held"

    @mcp.tool(read_only=True, concurrent=True)
    async def peek() -> str:
        log.append("peek")
        return "peeked"

    @mcp.tool
    def poke() -> str:
        log.append("poke")
        return "poked"

    holding = asyncio.ensure_future(call_tool(mcp, "hold"))
    await asyncio.sleep(0)  # hold takes the lock

    # The concurrent tool is not held back...
    response = await asyncio.wait_for(call_tool(mcp, "peek"), 1)
    assert text_of(response) == "peeked"
    # ... another one waits for the lock
    poking = asyncio.ensure_future(call_tool(mcp, "poke"))
    await asyncio.sleep(0.01)
    assert not poking.done()

    release.set()
    await asyncio.gather(holding, poking)
    assert log == ["hold:start", "peek", "hold:end", "poke"]


def test_bound_methods_carry_concurrent(mcp):
    class ProtoJobs:
        async def wait_for_jobs(self) -> str:
            return "idle"

        def start_job(self) -> str:
            return "started"

    jobs = ProtoJobs()
    mcp.tool(jobs.wait_for_jobs, read_only=True, concurrent=True)
    mcp.tool(jobs.start_job)
    assert mcp.get_tool("wait_for_jobs").concurrent is True
    assert mcp.get_tool("start_job").concurrent is False


@pytest.mark.asyncio
async def test_cancelled_tool_call_stops_releases_the_lock_and_flushes(mcp):
    state = mcp.server.state
    state.progress = 0
    state.ready()
    seen, log = [], []

    @state.change("progress")
    def on_progress(progress, **_):
        seen.append(progress)

    @mcp.tool
    async def long_job() -> str:
        state.progress = 50
        try:
            await asyncio.Event().wait()  # never set
        finally:
            log.append("cleaned up")
        return "done"

    @mcp.tool
    def quick() -> str:
        return "quick"

    job = asyncio.ensure_future(call_tool(mcp, "long_job", rpc_id=7))
    await asyncio.sleep(0.01)
    assert not job.done()

    assert mcp.protocol.cancel(8) is False  # not running
    assert await mcp.protocol.handle(cancel_notification(7, "user stopped")) is None
    response = await asyncio.wait_for(job, 1)
    assert response["id"] == 7
    assert response["error"] == {
        "code": REQUEST_CANCELLED,
        "message": "Request cancelled: user stopped",
    }
    assert log == ["cleaned up"]
    assert seen == [50]  # what it changed before the cancel was flushed

    # The lock is free again
    response = await asyncio.wait_for(call_tool(mcp, "quick"), 1)
    assert text_of(response) == "quick"
    assert not mcp.protocol._in_flight


@pytest.mark.asyncio
async def test_cancel_reaches_only_the_requests_of_its_session(mcp):
    release = asyncio.Event()

    @mcp.tool(concurrent=True)
    async def wait_for_release() -> str:
        await release.wait()
        return "released"

    message = rpc("tools/call", {"name": "wait_for_release"}, rpc_id=1)
    first = asyncio.ensure_future(mcp.protocol.handle(message, session="a"))
    second = asyncio.ensure_future(mcp.protocol.handle(message, session="b"))
    await asyncio.sleep(0.01)

    await mcp.protocol.handle(cancel_notification(1), session="a")
    response = await asyncio.wait_for(first, 1)
    assert response["error"] == {
        "code": REQUEST_CANCELLED,
        "message": "Request cancelled",
    }
    assert not second.done()

    # Unknown, finished and malformed requests are ignored
    await mcp.protocol.handle(cancel_notification(1), session="a")
    await mcp.protocol.handle(cancel_notification(99), session="b")
    await mcp.protocol.handle(cancel_notification([1]), session="b")
    await mcp.protocol.handle(
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": "x"}
    )
    assert not second.done()

    release.set()
    response = await asyncio.wait_for(second, 1)
    assert text_of(response) == "released"


@pytest.mark.asyncio
async def test_a_call_cancelled_while_waiting_for_the_lock_never_runs(mcp):
    release = asyncio.Event()
    log = []

    @mcp.tool
    async def hold() -> str:
        await release.wait()
        return "held"

    @mcp.tool
    def poke() -> str:
        log.append("poke")
        return "poked"

    holding = asyncio.ensure_future(call_tool(mcp, "hold", rpc_id=1))
    poking = asyncio.ensure_future(call_tool(mcp, "poke", rpc_id=2))
    await asyncio.sleep(0.01)
    await mcp.protocol.handle(cancel_notification(2))
    assert "error" in await asyncio.wait_for(poking, 1)

    release.set()
    assert "result" in await asyncio.wait_for(holding, 1)
    assert log == []
    response = await asyncio.wait_for(call_tool(mcp, "poke"), 1)
    assert text_of(response) == "poked"


@pytest.mark.asyncio
async def test_a_call_cancelled_from_outside_is_not_answered(mcp):
    """The client went away (the HTTP side cancels the task): the
    cancellation propagates instead of becoming a reply."""
    started = asyncio.Event()

    @mcp.tool
    async def wait_forever() -> str:
        started.set()
        await asyncio.Event().wait()
        return "done"

    @mcp.tool
    def quick() -> str:
        return "quick"

    handling = asyncio.ensure_future(call_tool(mcp, "wait_forever", rpc_id=3))
    await started.wait()
    handling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handling
    assert not mcp.protocol._in_flight
    # The lock was released
    response = await asyncio.wait_for(call_tool(mcp, "quick"), 1)
    assert text_of(response) == "quick"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("tools/call", {"name": ["add"]}),
        ("resources/read", {"uri": {"path": "info"}}),
        ("prompts/get", {"name": ["walkthrough"]}),
    ],
)
async def test_a_malformed_name_is_invalid_params(protocol, method, params):
    response = await protocol.handle(rpc(method, params))
    assert response["error"]["code"] == INVALID_PARAMS
