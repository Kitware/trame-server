"""Agents inside the application's process (``server.mcp.client()``): the
same rules as agents connected over a transport, with no transport."""

import asyncio
import itertools

import pytest
from trame.app import get_server

from trame_server.mcp import MCPClient, MCPError
from trame_server.mcp.protocol import INVALID_PARAMS, INVALID_REQUEST

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)

_counter = itertools.count()

DISABLED = "MCP access is currently disabled by the application"


def new_server():
    return get_server(f"test_mcp_client_{next(_counter)}")


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def declare(mcp):
    @mcp.tool
    def add(a: int, b: int = 1) -> int:
        """Add two numbers."""
        return a + b

    @mcp.tool
    def failing():
        msg = "boom"
        raise RuntimeError(msg)

    @mcp.resource("trame://info", mime_type="text/plain")
    def info():
        return "An app."

    @mcp.prompt
    def review(topic: str) -> str:
        """Review something."""
        return f"Review the {topic}"


@pytest.fixture
def mcp():
    mcp = new_server().mcp
    mcp.configure(enabled=True, transports=[])  # no transport needed
    declare(mcp)
    return mcp


@pytest.mark.asyncio
async def test_tools(mcp):
    client = mcp.client()
    assert isinstance(client, MCPClient)
    assert client.name == "in-process"

    tools = {tool["name"]: tool for tool in await client.list_tools()}
    assert tools["add"]["description"] == "Add two numbers."
    assert tools["add"]["inputSchema"]["required"] == ["a"]

    # The result as MCP defines it, without what only transports need
    assert await client.call_tool("add", {"a": 2}) == {
        "content": [{"type": "text", "text": "3"}]
    }

    # A failing tool still answers: its result says it failed
    failed = await client.call_tool("failing")
    assert failed["isError"] is True
    assert "boom" in failed["content"][0]["text"]
    invalid = await client.call_tool("add", {"a": "x"})
    assert invalid["isError"] is True
    assert "expected integer" in invalid["content"][0]["text"]


@pytest.mark.asyncio
async def test_what_the_server_cannot_serve_raises(mcp):
    client = mcp.client()
    with pytest.raises(MCPError, match="Unknown tool: missing") as caught:
        await client.call_tool("missing")
    assert caught.value.code == INVALID_PARAMS
    with pytest.raises(MCPError, match="Unknown resource"):
        await client.read_resource("trame://nope")
    with pytest.raises(MCPError, match="Unknown prompt"):
        await client.get_prompt("nope")


@pytest.mark.asyncio
async def test_resources_and_prompts(mcp):
    client = mcp.client()
    assert [r["uri"] for r in await client.list_resources()] == ["trame://info"]
    assert await client.read_resource("trame://info") == [
        {"uri": "trame://info", "mimeType": "text/plain", "text": "An app."}
    ]

    (prompt,) = await client.list_prompts()
    assert prompt["name"] == "review"
    assert await client.get_prompt("review", {"topic": "cone"}) == {
        "description": "Review something.",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "Review the cone"}}
        ],
    }


@pytest.mark.asyncio
async def test_instructions(mcp):
    mcp.instructions = "A test app."
    assert mcp.client().instructions == mcp._agent_instructions()
    assert mcp.client().instructions.startswith("A test app.")


@pytest.mark.asyncio
async def test_access_follows_enabled(mcp):
    client = mcp.client()
    mcp.enabled = False
    refused = await client.call_tool("add", {"a": 1})
    assert refused == {"content": [{"type": "text", "text": DISABLED}], "isError": True}
    with pytest.raises(MCPError, match=DISABLED) as caught:
        await client.read_resource("trame://info")
    assert caught.value.code == INVALID_REQUEST

    mcp.enabled = True
    assert (await client.call_tool("add", {"a": 1}))["content"][0]["text"] == "2"


@pytest.mark.asyncio
async def test_no_mcp_refuses_agents_in_the_process(monkeypatch):
    # trame reads TRAME_ARGS instead of sys.argv when running under pytest
    monkeypatch.setenv("TRAME_ARGS", "--no-mcp")
    mcp = new_server().mcp
    declare(mcp)
    mcp.enabled = True  # --no-mcp holds for the run
    assert (await mcp.client().call_tool("add", {"a": 1}))["isError"] is True


@pytest.mark.asyncio
async def test_permissions_apply(mcp):
    mcp.permissions.declare("math", "Do arithmetic")

    @mcp.tool(requires="math")
    def double(x: int) -> int:
        return 2 * x

    client = mcp.client()
    assert (await client.call_tool("double", {"x": 2}))["content"][0]["text"] == "4"
    mcp.permissions["math"] = False
    assert "double" not in [t["name"] for t in await client.list_tools()]
    assert (await client.call_tool("double", {"x": 2}))["isError"] is True


@pytest.mark.asyncio
async def test_cancelling_the_awaiting_task_cancels_the_call(mcp):
    started, cleaned_up = asyncio.Event(), asyncio.Event()

    @mcp.tool
    async def wait_forever() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()

    call = asyncio.ensure_future(mcp.client().call_tool("wait_forever"))
    await asyncio.wait_for(started.wait(), 1)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await asyncio.wait_for(cleaned_up.wait(), 1)
    # the tool lock was released
    assert (await mcp.client().call_tool("add", {"a": 1}))["content"][0]["text"] == "2"


@pytest.mark.asyncio
async def test_each_client_has_its_own_requests(mcp):
    """Both clients number their requests from 1: cancelling one's request
    leaves the other's alone."""
    mcp.concurrent_calls = True
    started = {"a": asyncio.Event(), "b": asyncio.Event()}
    release = asyncio.Event()

    @mcp.tool
    async def wait(who: str) -> str:
        started[who].set()
        await release.wait()
        return who

    a, b = mcp.client("a"), mcp.client("b")
    call_a = asyncio.ensure_future(a.call_tool("wait", {"who": "a"}))
    call_b = asyncio.ensure_future(b.call_tool("wait", {"who": "b"}))
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in started.values())), 1)

    assert mcp.protocol.cancel(1, session=a) is True
    release.set()
    with pytest.raises(MCPError, match="Request cancelled"):
        await call_a
    assert (await call_b)["content"][0]["text"] == "b"
