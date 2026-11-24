"""The call log (``--mcp-log``): what agents call, logged once whichever way
the call came in, through the standard ``logging`` module."""

import asyncio
import itertools
import logging
import re

import pytest
from trame.app import get_server

from trame_server.mcp import Image
from trame_server.mcp.call_log import shorten

SESSION = "abcdef0123456789"
LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)
MCP_LOGGER = logging.getLogger("trame_server.mcp")

_counter = itertools.count()


def rpc(method, params=None, rpc_id=1):
    msg = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pristine_logger():
    """The MCP loggers as an application that never configured logging has
    them (WARNING, Python's default; pytest lowers the root logger's),
    restored afterwards (they are process-wide)."""
    saved = MCP_LOGGER.handlers[:], MCP_LOGGER.level
    MCP_LOGGER.handlers.clear()
    MCP_LOGGER.setLevel(logging.WARNING)
    yield MCP_LOGGER
    MCP_LOGGER.handlers[:], MCP_LOGGER.level = saved


@pytest.fixture
def lines(pristine_logger):
    """Every line the MCP loggers write, through a handler of the
    application's own."""
    handler = _Lines()
    pristine_logger.addHandler(handler)
    return handler.lines


@pytest.fixture
def logging_on(pristine_logger):
    """What --mcp-log does: the MCP loggers at INFO."""
    pristine_logger.setLevel(logging.INFO)


def new_server():
    return get_server(f"test_mcp_call_log_{next(_counter)}")


@pytest.fixture
def mcp(pristine_logger):  # noqa: ARG001 - whatever a test turns on is undone
    mcp = new_server().mcp
    mcp.enabled = True
    return mcp


@pytest.fixture
def tools(mcp):
    @mcp.tool
    def add(a: int, b: int = 1) -> int:
        return a + b

    @mcp.tool
    def failing():
        msg = "boom"
        raise RuntimeError(msg)

    @mcp.tool
    def echo(text: str) -> str:
        return text

    @mcp.tool
    def snapshot() -> list:
        return [Image(b"\x89PNG" * 10), "a view"]

    @mcp.resource("trame://info", mime_type="application/json")
    def info():
        return {"name": "test"}

    @mcp.prompt
    def walkthrough(topic: str = "app") -> str:
        return f"Explain the {topic}"

    return mcp


@pytest.mark.asyncio
async def test_off_by_default(tools, lines):
    await tools.protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 2}})
    )
    assert lines == []


@pytest.mark.asyncio
async def test_a_call_is_logged_once_when_it_ends(tools, lines, logging_on):  # noqa: ARG001
    response = await tools.protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 2}}), session=SESSION
    )
    assert response["result"]["content"][0]["text"] == "3"
    (line,) = lines
    assert re.fullmatch(r"mcp\[abcdef\] add \{a: 2\} -> ok \d+\.\d\ds", line), line


@pytest.mark.asyncio
async def test_resources_and_prompts_too(tools, lines, logging_on):  # noqa: ARG001
    await tools.protocol.handle(rpc("resources/read", {"uri": "trame://info"}))
    await tools.protocol.handle(rpc("prompts/get", {"name": "walkthrough"}))
    resource, prompt = lines
    assert re.fullmatch(r"mcp\[-\] resource trame://info -> ok \d+\.\d\ds", resource)
    assert re.fullmatch(r"mcp\[-\] prompt walkthrough -> ok \d+\.\d\ds", prompt)


@pytest.mark.asyncio
async def test_in_process_calls_are_logged_too(tools, lines, logging_on):  # noqa: ARG001
    client = tools.client()
    await client.call_tool("add", {"a": 1})
    await client.read_resource("trame://info")
    assert lines[0].startswith("mcp[in-process] add {a: 1} -> ok")
    assert lines[1].startswith("mcp[in-process] resource trame://info -> ok")


@pytest.mark.asyncio
async def test_clients_without_a_session_are_named_by_themselves(
    tools,
    lines,
    logging_on,  # noqa: ARG001
):
    """In-process clients and clients of MCP 2026-07-28 have no session id:
    the name they give (clientInfo) says who called, kept to safe
    characters."""
    await tools.client().call_tool("add", {"a": 1})
    await tools.client("assistant").call_tool("add", {"a": 1})
    await tools.client("my agent\n[x]").call_tool("add", {"a": 1})
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "claude-code", "version": "2"},
    }
    await tools.protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 1}, "_meta": meta})
    )
    callers = [line.split("]")[0] + "]" for line in lines]
    assert callers == [
        "mcp[in-process]",
        "mcp[assistant]",
        "mcp[my_agent__x_]",  # no newline or bracket of the name's own
        "mcp[claude-code]",
    ]


@pytest.mark.asyncio
async def test_failures_say_what_the_agent_saw(tools, lines, logging_on):  # noqa: ARG001
    await tools.protocol.handle(rpc("tools/call", {"name": "failing"}))
    await tools.protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": "x"}})
    )
    await tools.protocol.handle(
        rpc("tools/call", {"name": "missing", "arguments": {"q": 1}})
    )
    await tools.protocol.handle(rpc("resources/read", {"uri": "trame://nope"}))
    # One line each: the failure is not logged a second time
    failing, invalid, unknown, resource = (
        line for line in lines if not line.startswith("Tool failing raised")
    )
    assert re.match(
        r"mcp\[-\] failing -> error \d+\.\d\ds: RuntimeError: boom$", failing
    )
    assert 'add {a: "x"} -> error' in invalid
    assert invalid.endswith(
        "Invalid arguments for tool add: arguments.a: expected integer, got string"
    )
    assert unknown.startswith("mcp[-] missing {q: 1} -> error")
    assert unknown.endswith("Unknown tool: missing")
    assert resource.startswith("mcp[-] resource trame://nope -> error")
    assert resource.endswith("Unknown resource: trame://nope")


@pytest.mark.asyncio
async def test_a_refused_permission_is_logged_as_denied(tools, lines, logging_on):  # noqa: ARG001
    tools.permissions.declare("files", "Read files", allowed=False)

    @tools.tool(requires="files")
    def read(path: str) -> str:
        return path

    await tools.protocol.handle(
        rpc("tools/call", {"name": "read", "arguments": {"path": "/"}})
    )
    (line,) = lines
    assert re.match(
        r'mcp\[-\] read \{path: "/"\} -> denied \d+\.\d\ds: read: permission "files" '
        r"\(Read files\) is off",
        line,
    ), line


@pytest.mark.asyncio
async def test_disabled_access_is_logged(tools, lines, logging_on):  # noqa: ARG001
    tools.enabled = False
    await tools.protocol.handle(
        rpc("tools/call", {"name": "add", "arguments": {"a": 1}})
    )
    (line,) = lines
    assert "-> error" in line
    assert line.endswith("MCP access is currently disabled by the application")


@pytest.mark.asyncio
async def test_a_cancelled_call(mcp, lines, logging_on):  # noqa: ARG001
    started = asyncio.Event()

    @mcp.tool
    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    handling = asyncio.ensure_future(
        mcp.protocol.handle(rpc("tools/call", {"name": "wait_forever"}, rpc_id=7))
    )
    await started.wait()
    await mcp.protocol.handle(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 7},
        }
    )
    await handling
    calls = [line for line in lines if line.startswith("mcp[")]
    (line,) = calls
    assert re.fullmatch(r"mcp\[-\] wait_forever -> cancelled \d+\.\d\ds", line), line


@pytest.mark.asyncio
async def test_long_arguments_are_shortened(tools, lines, logging_on):  # noqa: ARG001
    await tools.protocol.handle(
        rpc("tools/call", {"name": "echo", "arguments": {"text": "x" * 500}})
    )
    assert lines[0].startswith("mcp[-] echo {text: <str 500 chars>} -> ok")


def test_shorten():
    assert (
        shorten({"a": 1, "b": [True, None], "c": "hi"})
        == '{a: 1, b: [true, null], c: "hi"}'
    )
    assert shorten(list(range(10))) == "[0, 1, 2, 3, 4, 5, 6, 7, +2]"
    assert shorten({str(i): i for i in range(9)}).endswith(", 7: 7, +1}")
    assert shorten({"a": {"b": {"c": {"d": 1}}}}) == "{a: {b: {c: {...}}}}"
    assert shorten([[[[1]]]]) == "[[[[...]]]]"
    assert shorten(object()) == "<object>"
    assert shorten(1.5) == "1.5"


@pytest.mark.parametrize("variable", ["TRAME_ARGS", "TRAME_MCP_LOG"])
def test_the_launch_flag_sets_the_level(monkeypatch, pristine_logger, variable):
    # trame reads TRAME_ARGS instead of sys.argv when running under pytest
    monkeypatch.setenv(variable, "--mcp-log" if variable == "TRAME_ARGS" else "1")
    new_server().mcp  # noqa: B018 - created, it applies the launch options
    assert pristine_logger.level == logging.INFO
    # A level only: where the lines go is the application's choice
    assert pristine_logger.handlers == []


def test_the_launch_flag_keeps_a_finer_level(monkeypatch, pristine_logger):
    pristine_logger.setLevel(logging.DEBUG)
    monkeypatch.setenv("TRAME_ARGS", "--mcp-log")
    new_server().mcp  # noqa: B018
    assert pristine_logger.level == logging.DEBUG
