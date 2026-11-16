"""Progress (``Progress`` parameters): what a long tool or method reports,
sent to the agent that asked for it."""

import asyncio
import itertools
import json
import logging

import aiohttp
import pytest
from trame.app import get_server
from trame_common.decorators import mcp as mcp_decorators
from trame_common.obj.component import TrameComponent

from trame_server.mcp import Progress
from trame_server.mcp.progress import Reporter

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)

_counter = itertools.count()


def new_server():
    return get_server(f"test_mcp_progress_{next(_counter)}")


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


class Loader(TrameComponent):
    """Loads files."""

    @mcp_decorators.method
    async def load(self, path: str, progress: Progress | None = None) -> str:
        """Load a file."""
        self.received = progress
        if progress:
            await progress(1, total=2, message="Reading")
            await asyncio.sleep(0.15)  # past the interval: sent apart
            await progress(2, total=2, message="Done")
        return f"Loaded {path}"

    @mcp_decorators.method
    async def scan(self, progress: Progress | None = None) -> str:
        """Find files, not knowing how many there are."""
        if progress:
            for found in (1, 2):
                await progress(found, message=f"Found {found}")
                await asyncio.sleep(0.15)
        return "Scanned"


@pytest.fixture
def mcp():
    server = new_server()
    mcp = server.mcp
    mcp.configure(enabled=True, transports=[])

    @mcp.tool
    async def crunch(steps: int, progress: Progress | None = None) -> str:
        """Crunch some numbers."""
        for step in range(1, steps + 1):
            await progress(step, total=steps, message=f"Step {step}")
            await asyncio.sleep(0.15)
        return "Crunched"

    loader = Loader(server)
    loader.mcp_expose("loader")
    mcp.loader = loader  # kept alive for the test
    return mcp


def collector():
    reports = []

    def on_progress(value, total, message):
        reports.append((value, total, message))

    return reports, on_progress


# -----------------------------------------------------------------------------
# Declaring
# -----------------------------------------------------------------------------


def test_agents_dont_see_the_parameter(mcp):
    (tool,) = [t for t in mcp.list_tools() if t.name == "crunch"]
    schema = mcp._input_schema(tool)
    assert list(schema["properties"]) == ["steps"]
    assert schema["additionalProperties"] is False

    parameters = mcp.describe(Loader)["methods"]["load"]["parameters"]
    assert list(parameters["properties"]) == ["path"]


def test_reports_are_awaited_so_it_takes_async(mcp):
    def sync_crunch(progress: Progress | None = None) -> str:  # noqa: ARG001
        return "no"

    with pytest.raises(TypeError, match="Tool 'sync_crunch': a Progress parameter"):
        mcp.tool(sync_crunch)

    class SyncLoader(TrameComponent):
        @mcp_decorators.method
        def load(self, progress: Progress | None = None) -> str:  # noqa: ARG002
            return "no"

    with pytest.raises(TypeError, match=r"SyncLoader\.load: a Progress parameter"):
        mcp.describe(SyncLoader)


@pytest.mark.asyncio
async def test_the_apps_own_calls_get_the_default(mcp):
    assert await mcp.loader.load("a.vtk") == "Loaded a.vtk"
    assert mcp.loader.received is None


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_tool_reports_to_the_agent_that_asked(mcp):
    reports, on_progress = collector()
    result = await mcp.client().call_tool(
        "crunch", {"steps": 3}, on_progress=on_progress
    )
    assert result["content"][0]["text"] == "Crunched"
    assert reports == [(1, 3, "Step 1"), (2, 3, "Step 2"), (3, 3, "Step 3")]


@pytest.mark.asyncio
async def test_without_asking_nothing_is_reported(mcp):
    client = mcp.client()
    result = await client.call_tool("crunch", {"steps": 2})
    assert result["content"][0]["text"] == "Crunched"  # a reporter that does nothing

    await client.call_tool(
        "object_call", {"target": "loader", "method": "load", "args": {"path": "a"}}
    )
    assert type(mcp.loader.received) is Progress  # not None: an agent's call


@pytest.mark.asyncio
async def test_a_method_reports_through_object_call(mcp):
    reports, on_progress = collector()
    result = await mcp.client().call_tool(
        "object_call",
        {"target": "loader", "method": "load", "args": {"path": "a.vtk"}},
        on_progress=on_progress,
    )
    assert result["content"][0]["text"] == "Loaded a.vtk"
    assert reports == [(1, 2, "Reading"), (2, 2, "Done")]


@pytest.mark.asyncio
async def test_a_batch_reports_its_steps(mcp):
    """Step k of n, a method's own report counting within its step."""
    reports, on_progress = collector()
    steps = [
        {"call": "loader", "method": "load", "args": {"path": "a"}},
        {"call": "loader", "method": "load", "args": {"path": "b"}},
    ]
    result = await mcp.client().call_tool(
        "object_batch", {"steps": steps}, on_progress=on_progress
    )
    assert "isError" not in result
    values = [value for value, _, _ in reports]
    assert values == sorted(set(values))  # always growing
    assert all(total == 2 for _, total, _ in reports)
    assert values[-1] == 2
    assert (0.5, 2, "Reading") in reports  # the first load, half way


@pytest.mark.asyncio
async def test_a_batch_step_without_a_total_still_reports(mcp):
    """Each report moves the value a little within its step, so it goes out
    while the step runs, with its message."""
    reports, on_progress = collector()
    steps = [
        {"call": "loader", "method": "load", "args": {"path": "a"}},
        {"call": "loader", "method": "scan"},
    ]
    result = await mcp.client().call_tool(
        "object_batch", {"steps": steps}, on_progress=on_progress
    )
    assert "isError" not in result
    assert reports[-3:] == [
        (1.00000001, 2, "Found 1"),
        (1.00000002, 2, "Found 2"),
        (2, 2, None),
    ]


@pytest.mark.asyncio
async def test_a_failing_callback_doesnt_stop_the_call(mcp, caplog):
    def on_progress(*_):
        msg = "broken UI"
        raise RuntimeError(msg)

    with caplog.at_level(logging.ERROR, logger="trame_server.mcp"):
        result = await mcp.client().call_tool(
            "crunch", {"steps": 1}, on_progress=on_progress
        )
    assert result["content"][0]["text"] == "Crunched"
    assert "on_progress failed" in caplog.text


@pytest.mark.asyncio
async def test_an_async_callback(mcp):
    reports = []

    async def on_progress(value, _total, _message):
        await asyncio.sleep(0)
        reports.append(value)

    await mcp.client().call_tool("crunch", {"steps": 2}, on_progress=on_progress)
    assert reports == [1, 2]


# -----------------------------------------------------------------------------
# The reporter's rules
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_are_combined_the_latest_winning():
    sent = []

    async def send(fields):
        sent.append(fields)

    reporter = Reporter(send, interval=0.05)
    for value in range(1, 11):
        await reporter(value, total=10)
    assert sent == [{"progress": 1, "total": 10}]  # the rest is due later
    await asyncio.sleep(0.08)
    assert sent[-1] == {"progress": 10, "total": 10}
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_a_value_must_grow():
    sent = []

    async def send(fields):
        sent.append(fields)

    reporter = Reporter(send, interval=0)
    await reporter(5)
    await reporter(5, message="Still at five")  # dropped, its message kept
    await reporter(3)
    await reporter(6)
    assert sent == [{"progress": 5}, {"progress": 6, "message": "Still at five"}]


@pytest.mark.asyncio
async def test_what_is_pending_goes_before_the_result_then_nothing():
    sent = []

    async def send(fields):
        sent.append(fields)

    reporter = Reporter(send, interval=0.05)
    await reporter(1)
    await reporter(2)  # due later
    await reporter.close()  # the result is ready
    assert sent == [{"progress": 1}, {"progress": 2}]
    await reporter(3)
    await asyncio.sleep(0.08)
    assert sent == [{"progress": 1}, {"progress": 2}]


@pytest.mark.asyncio
async def test_a_send_that_fails_stops_the_reports_not_the_call():
    calls = []

    async def send(fields):
        calls.append(fields)
        raise ConnectionResetError

    reporter = Reporter(send, interval=0)
    await reporter(1)
    await reporter(2)
    assert calls == [{"progress": 1}]


# -----------------------------------------------------------------------------
# Over HTTP: Server-Sent Events once there is something to report
# -----------------------------------------------------------------------------


async def start(server):
    server.start(
        exec_mode="task",
        port=0,
        open_browser=False,
        show_connection_info=False,
        disable_logging=True,
    )
    await server.ready


def tool_call(name, arguments, token=None):
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    if token is not None:
        meta["progressToken"] = token
    message = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments, "_meta": meta},
    }
    headers = {
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": name,
        "Accept": "application/json, text/event-stream",
    }
    return message, headers


def events(text):
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_over_http(mcp):
    server = mcp.server
    mcp.transports = ["http"]
    await start(server)
    url = f"http://localhost:{server.port}/mcp"
    try:
        async with aiohttp.ClientSession() as session:
            # Asked for: the notifications, then the response, as events
            message, headers = tool_call("crunch", {"steps": 2}, token="t1")
            async with session.post(url, json=message, headers=headers) as resp:
                assert resp.status == 200
                assert resp.headers["Content-Type"].startswith("text/event-stream")
                assert resp.headers["X-Accel-Buffering"] == "no"
                received = events(await resp.text())
            *notifications, response = received
            assert [n["params"] for n in notifications] == [
                {"progressToken": "t1", "progress": 1, "total": 2, "message": "Step 1"},
                {"progressToken": "t1", "progress": 2, "total": 2, "message": "Step 2"},
            ]
            assert {n["method"] for n in notifications} == {"notifications/progress"}
            assert response["id"] == 7
            assert response["result"]["content"][0]["text"] == "Crunched"

            # Not asked for, or a client that takes no event stream: plain JSON
            message, headers = tool_call("crunch", {"steps": 1})
            async with session.post(url, json=message, headers=headers) as resp:
                assert resp.headers["Content-Type"].startswith("application/json")
            message, headers = tool_call("crunch", {"steps": 1}, token="t2")
            headers["Accept"] = "application/json"
            async with session.post(url, json=message, headers=headers) as resp:
                assert resp.headers["Content-Type"].startswith("application/json")
                assert (await resp.json())["result"]["content"][0]["text"] == "Crunched"
    finally:
        await server.stop()
