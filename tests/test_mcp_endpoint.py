"""The HTTP endpoint (``server.mcp.http``): the web-server-agnostic handler
with fake requests, then end to end on a real trame server."""

import asyncio
import base64
import itertools
import json
import logging
import shlex
from types import SimpleNamespace

import aiohttp
import pytest
import pytest_asyncio
from trame.app import get_server
from trame_common.decorators.mcp import mcp_method
from trame_common.obj.component import TrameComponent

from trame_server.mcp import endpoint
from trame_server.mcp.endpoint import (
    HTTPRequest,
    MCPEndpoint,
    aiohttp_routes,
    claude_command,
    codex_command,
    is_loopback,
    mount,
)
from trame_server.mcp.protocol import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    REQUEST_CANCELLED,
    UNSUPPORTED_VERSION,
)

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)
DISABLED = "MCP access is currently disabled by the application"

_counter = itertools.count()


def rpc(method, params=None, rpc_id=1):
    msg = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def modern(method, params=None, rpc_id=1, version="2026-07-28"):
    """A request as clients of 2026-07-28 send it: its version and the
    client's capabilities in _meta."""
    meta = {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return rpc(method, {**(params or {}), "_meta": meta}, rpc_id=rpc_id)


def mirrored(message):
    """The headers a 2026-07-28 client sends with ``message``."""
    params = message["params"]
    headers = {
        "MCP-Protocol-Version": params["_meta"][
            "io.modelcontextprotocol/protocolVersion"
        ],
        "Mcp-Method": message["method"],
    }
    field = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
    if message["method"] in field:
        headers["Mcp-Name"] = params[field[message["method"]]]
    return headers


def new_server():
    return get_server(f"test_mcp_endpoint_{next(_counter)}")


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


# -----------------------------------------------------------------------------
# The handler, with fake requests
# -----------------------------------------------------------------------------


def request(
    message=None,
    *,
    headers=None,
    host="localhost",
    authority="localhost:8080",
    content_type="application/json",
    disconnected=lambda: False,
):
    """A request as a web server adapter hands it to the endpoint."""
    if isinstance(message, bytes):
        body = message
    else:
        body = json.dumps(rpc("ping") if message is None else message).encode()
    all_headers = {"content-type": content_type} if content_type else {}
    all_headers.update({k.lower(): v for k, v in (headers or {}).items()})

    async def read():
        return body

    return HTTPRequest(
        method="POST",
        headers=all_headers,
        host=host,
        authority=authority,
        read=read,
        disconnected=disconnected,
    )


@pytest.fixture
def mcp():
    mcp = new_server().mcp
    mcp.enabled = True
    return mcp


@pytest.fixture
def handler(mcp):
    return MCPEndpoint(mcp.server)


def test_is_loopback():
    for host in (
        "localhost",
        "LOCALHOST",
        "app.localhost",
        "127.0.0.1",
        "127.8.0.1",
        "::1",
        "[::1]",
    ):
        assert is_loopback(host), host
    for host in (
        None,
        "",
        "0.0.0.0",
        "::",
        "192.168.1.5",
        "example.com",
        "localhost.evil.com",
    ):
        assert not is_loopback(host), host


@pytest.mark.asyncio
async def test_before_server_mcp_exists_it_answers_503():
    server = new_server()
    child = server.create_child_server(prefix="child_")
    for handler in (MCPEndpoint(server), MCPEndpoint(child)):
        response = await handler.post(request())
        assert response.status == 503
        assert response.body == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32000, "message": DISABLED},
        }
    assert server._mcp is None  # a request does not create it


@pytest.mark.asyncio
async def test_a_request_reaches_the_protocol(handler):
    response = await handler.post(request(rpc("ping", rpc_id=4)))
    assert response.status == 200
    assert response.body == {"jsonrpc": "2.0", "id": 4, "result": {}}
    assert response.headers == {}

    # an invalid JSON-RPC message is answered in the body
    response = await handler.post(request({"jsonrpc": "1.0", "id": 1}))
    assert response.status == 200
    assert response.body["error"]["code"] == INVALID_REQUEST


@pytest.mark.asyncio
async def test_initialize_gives_each_client_a_session(handler):
    first = await handler.post(request(rpc("initialize", {})))
    second = await handler.post(request(rpc("initialize", {})))
    assert first.status == second.status == 200
    session = first.headers["Mcp-Session-Id"]
    assert len(session) >= 24
    assert second.headers["Mcp-Session-Id"] != session


@pytest.mark.asyncio
async def test_notifications_are_acknowledged_without_a_body(handler):
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    response = await handler.post(request(notification))
    assert (response.status, response.body) == (202, None)
    response = await handler.post(request({"jsonrpc": "2.0", "id": 9, "result": {}}))
    assert response.status == 202


@pytest.mark.asyncio
async def test_bodies_it_does_not_take(handler):
    for body in (b"{not json", b"\xff\xfe"):
        response = await handler.post(request(body))
        assert response.status == 400
        assert response.body["error"] == {"code": -32700, "message": "Parse error"}
    response = await handler.post(request([rpc("ping")]))
    assert response.status == 400
    assert response.body["error"] == {
        "code": -32600,
        "message": "JSON-RPC batching is not supported",
    }


def test_get_and_delete_are_not_supported():
    response = MCPEndpoint.unsupported()
    assert (response.status, response.body) == (405, None)
    assert response.headers == {"Allow": "POST"}


@pytest.mark.asyncio
async def test_the_checks_run_in_order(handler, mcp):
    evil = {"Origin": "https://evil.example"}

    # 1. Origin, before anything else
    mcp.enabled = False
    mcp.http.token = "s3cret"
    response = await handler.post(request(headers=evil, content_type="text/plain"))
    assert response.status == 403
    assert response.body["error"]["message"] == "Origin not allowed"

    # 2. the token
    response = await handler.post(request(content_type="text/plain"))
    assert response.status == 401
    assert response.headers == {"WWW-Authenticate": "Bearer"}

    # ... or without one, a loopback host
    mcp.http.token = None
    response = await handler.post(
        request(host="myhost.lan", authority="myhost.lan:8080", content_type=None)
    )
    assert response.status == 403
    assert "set a token" in response.body["error"]["message"]

    # 3. enabled
    response = await handler.post(request(content_type="text/plain"))
    assert response.status == 503

    # 4. the content type
    mcp.enabled = True
    for content_type in ("text/plain", None, "application/jsonx"):
        response = await handler.post(request(content_type=content_type))
        assert response.status == 415, content_type
    response = await handler.post(
        request(content_type="Application/JSON; charset=utf-8")
    )
    assert response.status == 200


@pytest.mark.asyncio
async def test_origins(handler, mcp):
    async def status(origin, **kwargs):
        response = await handler.post(request(headers={"Origin": origin}, **kwargs))
        return response.status

    assert await status("https://evil.example") == 403
    assert await status("null") == 403  # sandboxed frames, file://
    assert await status("not a url") == 403
    # Local browser tools (e.g. MCP Inspector)
    assert await status("http://localhost:6274") == 200
    assert await status("http://127.0.0.1:6274") == 200
    assert await status("http://[::1]:6274") == 200

    # Listed origins
    mcp.http.allowed_origins = "https://trusted.example/"
    assert mcp.http.allowed_origins == ("https://trusted.example",)
    assert await status("https://trusted.example") == 200
    assert await status("https://other.example") == 403

    # The page served next to the endpoint (its own origin)
    mcp.http.token = "s3cret"

    async def from_page(origin):
        response = await handler.post(
            request(
                headers={"Origin": origin, "Authorization": "Bearer s3cret"},
                host="app.example",
                authority="app.example:8443",
            )
        )
        return response.status

    assert await from_page("https://app.example:8443") == 200
    assert await from_page("https://app.example:9999") == 403


@pytest.mark.asyncio
async def test_the_token(handler, mcp):
    async def status(authorization=None, **kwargs):
        headers = {"Authorization": authorization} if authorization else {}
        return (await handler.post(request(headers=headers, **kwargs))).status

    mcp.http.token = "s3cret"
    assert await status() == 401
    assert await status("Bearer nope") == 401
    assert await status("Basic s3cret") == 401
    assert await status("Bearer s3cret") == 200
    assert await status("bearer s3cret") == 200
    # with a token, the host name is no longer restricted to loopback
    assert await status("Bearer s3cret", host="myhost.lan") == 200

    mcp.http.token = None
    assert await status() == 200
    assert await status(host="myhost.lan") == 403


@pytest.mark.asyncio
async def test_a_client_that_disconnects_cancels_its_call(handler, mcp, monkeypatch):
    monkeypatch.setattr(endpoint, "DISCONNECT_POLL", 0.01)
    started, cleaned_up = asyncio.Event(), asyncio.Event()
    gone = False

    @mcp.tool
    async def wait_forever() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()
        return "done"

    @mcp.tool
    def quick() -> str:
        return "quick"

    posting = asyncio.ensure_future(
        handler.post(
            request(
                rpc("tools/call", {"name": "wait_forever"}),
                disconnected=lambda: gone,
            )
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    gone = True
    response = await asyncio.wait_for(posting, 1)
    assert (response.status, response.body) == (499, None)
    assert response.reason == "Client Closed Request"
    assert cleaned_up.is_set()

    # The tool lock was released: the next call runs
    response = await asyncio.wait_for(
        handler.post(request(rpc("tools/call", {"name": "quick"}))), 1
    )
    assert response.body["result"]["content"][0]["text"] == "quick"


@pytest.mark.asyncio
async def test_a_session_scopes_cancellation(handler, mcp):
    started = asyncio.Event()

    @mcp.tool
    async def long_job() -> str:
        started.set()
        await asyncio.Event().wait()
        return "done"

    session = {"Mcp-Session-Id": "abc"}
    posting = asyncio.ensure_future(
        handler.post(
            request(rpc("tools/call", {"name": "long_job"}, rpc_id=3), headers=session)
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    cancel = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": 3},
    }
    response = await handler.post(request(cancel, headers={"Mcp-Session-Id": "xyz"}))
    assert response.status == 202
    await asyncio.sleep(0.01)
    assert not posting.done()
    await handler.post(request(cancel, headers=session))
    response = await asyncio.wait_for(posting, 1)
    assert response.status == 200
    assert response.body["error"]["code"] == REQUEST_CANCELLED


def test_aiohttp_routes():
    routes = aiohttp_routes(MCPEndpoint(new_server()), "/api/mcp")
    assert [(r.method, r.path) for r in routes] == [
        ("POST", "/api/mcp"),
        ("GET", "/api/mcp"),
        ("DELETE", "/api/mcp"),
    ]


def test_mount_needs_an_aiohttp_application(caplog):
    server = new_server()
    advice = "serve trame_server.mcp.endpoint.MCPEndpoint yourself"
    with caplog.at_level(logging.INFO, logger="trame_server.mcp"):
        assert mount(server, SimpleNamespace(app=object())) is False
        # only worth mentioning to an app that uses agents
        assert advice not in caplog.text
        server.mcp  # noqa: B018
        assert mount(server, SimpleNamespace()) is False
    assert advice in caplog.text


def test_the_claude_command_adds_the_server_for_one_session():
    assert claude_command("app", "http://localhost:8080/mcp") == (
        "claude --mcp-config "
        """'{"mcpServers":{"app":{"type":"http","url":"http://localhost:8080/mcp"}}}'"""
    )
    assert claude_command("app", "http://h:8080/mcp", "s3cret").endswith(
        """"headers":{"Authorization":"Bearer s3cret"}}}}'"""
    )
    # The JSON stays one shell word whatever the name holds
    assert shlex.split(claude_command("it's", "http://h/mcp"))[-1] == (
        """{"mcpServers":{"it's":{"type":"http","url":"http://h/mcp"}}}"""
    )


def test_the_codex_command_adds_the_server_for_one_session():
    assert codex_command("app", "http://localhost:8080/mcp") == (
        """codex -c 'mcp_servers.app.url="http://localhost:8080/mcp"'"""
    )
    assert codex_command("app", "http://h:8080/mcp", "s3cret") == (
        """codex -c 'mcp_servers.app.url="http://h:8080/mcp"' """
        """-c 'mcp_servers.app.http_headers={Authorization="Bearer s3cret"}'"""
    )


# -----------------------------------------------------------------------------
# End to end: a real trame server, MCP over HTTP
# -----------------------------------------------------------------------------


async def start(server, **kwargs):
    server.start(
        exec_mode="task",
        port=0,
        open_browser=False,
        show_connection_info=False,
        disable_logging=True,
        **kwargs,
    )
    await server.ready


async def post(session, server, message=None, path="/mcp", **kwargs):
    url = f"http://localhost:{server.port}{path}"
    if "data" not in kwargs:
        kwargs.setdefault("json", message or rpc("ping"))
    async with session.post(url, **kwargs) as resp:
        body = await resp.json(content_type=None) if resp.status != 202 else None
        return resp.status, body


async def status_of(session, server, path="/mcp", method="POST"):
    url = f"http://localhost:{server.port}{path}"
    kwargs = {"json": rpc("ping")} if method == "POST" else {}
    async with session.request(method, url, **kwargs) as resp:
        return resp.status, resp.headers.get("Allow", "")


@pytest_asyncio.fixture
async def running_server():
    server = new_server()
    mcp = server.mcp
    mcp.enabled = True

    server.state.resolution = 6
    server.state.mcp_expose("resolution", type=int)

    @mcp.tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    await start(server)
    yield server, mcp
    await server.stop()


@pytest.mark.asyncio
async def test_http_roundtrip(running_server):
    server, mcp = running_server
    url = f"http://localhost:{server.port}/mcp"
    assert mcp.http.url == url

    async with aiohttp.ClientSession() as session:
        # initialize: the preferred version, or the client's when it is known
        status, body = await post(session, server, rpc("initialize", {}))
        assert status == 200
        assert body["result"]["protocolVersion"] == "2025-11-25"
        _, body = await post(
            session, server, rpc("initialize", {"protocolVersion": "2025-06-18"})
        )
        assert body["result"]["protocolVersion"] == "2025-06-18"

        # initialized notification -> 202, empty
        status, _ = await post(
            session, server, {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert status == 202

        # tools/list
        _, body = await post(session, server, rpc("tools/list"))
        assert {"add", "object_get", "object_update"} <= {
            t["name"] for t in body["result"]["tools"]
        }

        # tools/call -> touches real trame state
        update = {"target": "state", "values": {"resolution": 24}}
        _, body = await post(
            session,
            server,
            rpc("tools/call", {"name": "object_update", "arguments": update}),
        )
        assert body["result"].get("isError") is None
        assert server.state.resolution == 24

        # schema-checked: a string never reaches the state
        update = {"target": "state", "values": {"resolution": "x"}}
        _, body = await post(
            session,
            server,
            rpc("tools/call", {"name": "object_update", "arguments": update}),
        )
        assert body["result"]["isError"] is True
        assert server.state.resolution == 24

        # GET and DELETE are not supported (stateless server)
        assert await status_of(session, server, method="GET") == (405, "POST")
        assert await status_of(session, server, method="DELETE") == (405, "POST")

        # batch rejected
        status, _ = await post(session, server, [rpc("ping")])
        assert status == 400

        # malformed json
        status, _ = await post(
            session,
            server,
            data=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400


@pytest.mark.asyncio
async def test_cross_site_requests_are_rejected(running_server):
    server, mcp = running_server
    attack = rpc(
        "tools/call",
        {
            "name": "object_update",
            "arguments": {"target": "state", "values": {"resolution": 99}},
        },
    )

    async with aiohttp.ClientSession() as session:
        # A page on another site: browsers attach its Origin
        status, _ = await post(
            session, server, attack, headers={"Origin": "https://evil.example"}
        )
        assert status == 403
        status, _ = await post(session, server, attack, headers={"Origin": "null"})
        assert status == 403

        # "Simple" request a browser sends without CORS preflight
        status, _ = await post(
            session, server, data=b"{}", headers={"Content-Type": "text/plain"}
        )
        assert status == 415

        # DNS rebinding: attacker domain resolved to 127.0.0.1, same-origin to
        # the browser
        rebound = f"evil.example:{server.port}"
        status, body = await post(
            session,
            server,
            attack,
            headers={"Host": rebound, "Origin": f"http://{rebound}"},
        )
        assert status == 403
        assert "set a token" in body["error"]["message"]

        assert server.state.resolution == 6

        # Local browser tools (e.g. MCP Inspector) and listed origins are fine
        status, _ = await post(
            session, server, headers={"Origin": "http://localhost:6274"}
        )
        assert status == 200
        mcp.http.allowed_origins = ["https://trusted.example/"]
        status, _ = await post(
            session, server, headers={"Origin": "https://trusted.example"}
        )
        assert status == 200


@pytest.mark.asyncio
async def test_a_2026_client(running_server):
    """No handshake and no session: each request names its version."""
    server, _ = running_server
    url = f"http://localhost:{server.port}/mcp"
    call = modern("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=call, headers=mirrored(call)) as resp:
            assert resp.status == 200
            assert "Mcp-Session-Id" not in resp.headers
            body = await resp.json()
        assert body["result"]["content"] == [{"type": "text", "text": "5"}]
        assert body["result"]["resultType"] == "complete"

        discover = modern("server/discover")
        status, body = await post(session, server, discover, headers=mirrored(discover))
        assert status == 200
        assert body["result"]["supportedVersions"][0] == "2026-07-28"


@pytest.mark.asyncio
async def test_a_2026_request_mirrors_its_body_in_headers(running_server):
    server, _ = running_server
    call = modern("tools/call", {"name": "add", "arguments": {"a": 1}})
    good = mirrored(call)

    async def send(headers, message=call):
        async with aiohttp.ClientSession() as session:
            return await post(session, server, message, headers=headers)

    for missing in good:
        status, body = await send({k: v for k, v in good.items() if k != missing})
        assert status == 400
        assert body["id"] == 1
        assert body["error"]["code"] == HEADER_MISMATCH
        assert f"the {missing} header is missing" in body["error"]["message"]

    for header in ("Mcp-Name", "Mcp-Method", "MCP-Protocol-Version"):
        status, body = await send({**good, header: "other"})
        assert status == 400
        assert "does not match body value" in body["error"]["message"]

    # A name outside plain ASCII is sent in the Base64 form
    encoded = "=?base64?" + base64.b64encode(b"add").decode() + "?="
    assert (await send({**good, "Mcp-Name": encoded}))[0] == 200
    assert (await send({**good, "Mcp-Name": "=?base64?not base64?="}))[0] == 400

    # Headers of 2026-07-28 on a body that doesn't name its version
    status, body = await send(
        {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"},
        message=rpc("tools/list"),
    )
    assert (status, body["error"]["code"]) == (400, HEADER_MISMATCH)


@pytest.mark.asyncio
async def test_a_2026_request_the_server_cannot_serve(running_server):
    server, _ = running_server

    async def send(message):
        async with aiohttp.ClientSession() as session:
            return await post(session, server, message, headers=mirrored(message))

    status, body = await send(modern("tools/list", version="2099-01-01"))
    assert (status, body["error"]["code"]) == (400, UNSUPPORTED_VERSION)
    assert body["error"]["data"]["requested"] == "2099-01-01"

    message = modern("tools/list")
    del message["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    status, body = await send(message)
    assert (status, body["error"]["code"]) == (400, INVALID_PARAMS)

    for method in ("ping", "initialize", "subscriptions/listen"):
        status, body = await send(modern(method))
        assert (status, body["id"], body["error"]["code"]) == (404, 1, METHOD_NOT_FOUND)


@pytest.mark.asyncio
async def test_token_auth(running_server):
    server, mcp = running_server
    mcp.http.token = "s3cret"

    async with aiohttp.ClientSession() as session:
        url = f"http://localhost:{server.port}/mcp"
        async with session.post(url, json=rpc("ping")) as resp:
            assert resp.status == 401
            assert resp.headers["WWW-Authenticate"] == "Bearer"
        status, _ = await post(
            session, server, headers={"Authorization": "Bearer nope"}
        )
        assert status == 401
        status, _ = await post(
            session, server, headers={"Authorization": "bearer s3cret"}
        )
        assert status == 200

        # with a token, the host name is no longer restricted to loopback
        status, _ = await post(
            session,
            server,
            headers={
                "Authorization": "Bearer s3cret",
                "Host": f"myhost.lan:{server.port}",
            },
        )
        assert status == 200

        mcp.http.token = None
        status, _ = await post(session, server)
        assert status == 200


@pytest.mark.asyncio
async def test_runtime_enable_switch(running_server):
    server, mcp = running_server

    async with aiohttp.ClientSession() as session:
        mcp.enabled = False
        status, body = await post(session, server)
        assert status == 503
        assert body == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32000, "message": DISABLED},
        }

        mcp.enabled = True
        status, _ = await post(session, server)
        assert status == 200


@pytest.mark.asyncio
async def test_path_is_fixed_once_started(running_server):
    _, mcp = running_server
    with pytest.raises(RuntimeError, match="started"):
        mcp.http.path = "/other"
    assert mcp.http.path == "/mcp"


@pytest.mark.asyncio
async def test_initialize_gives_a_session_that_scopes_cancellation(running_server):
    server, mcp = running_server
    url = f"http://localhost:{server.port}/mcp"
    started, cleaned_up = asyncio.Event(), asyncio.Event()

    @mcp.tool
    async def long_job() -> str:
        started.set()
        try:
            await asyncio.Event().wait()  # until cancelled
        finally:
            cleaned_up.set()
        return "done"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=rpc("initialize", {})) as resp:
            session_id = resp.headers["Mcp-Session-Id"]
        async with session.post(url, json=rpc("initialize", {})) as resp:
            assert resp.headers["Mcp-Session-Id"] != session_id  # one per client
        # other responses carry none
        async with session.post(url, json=rpc("ping")) as resp:
            assert "Mcp-Session-Id" not in resp.headers

        headers = {"Mcp-Session-Id": session_id}
        job = asyncio.ensure_future(
            post(
                session,
                server,
                rpc("tools/call", {"name": "long_job"}, rpc_id=3),
                headers=headers,
            )
        )
        await asyncio.wait_for(started.wait(), 2)

        cancel = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 3, "reason": "timed out"},
        }
        # Another session's cancel leaves it running
        status, _ = await post(
            session, server, cancel, headers={"Mcp-Session-Id": "other"}
        )
        assert status == 202
        await asyncio.sleep(0.05)
        assert not job.done()

        status, _ = await post(session, server, cancel, headers=headers)
        assert status == 202
        status, body = await asyncio.wait_for(job, 2)
        assert status == 200
        assert body["id"] == 3
        assert body["error"] == {
            "code": REQUEST_CANCELLED,
            "message": "Request cancelled: timed out",
        }
        assert cleaned_up.is_set()


@pytest.mark.asyncio
async def test_a_client_that_disconnects_over_http_cancels_its_call(
    running_server, monkeypatch
):
    monkeypatch.setattr(endpoint, "DISCONNECT_POLL", 0.02)
    server, mcp = running_server
    url = f"http://localhost:{server.port}/mcp"
    started, cleaned_up = asyncio.Event(), asyncio.Event()

    @mcp.tool
    async def wait_forever() -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()
        return "done"

    async with aiohttp.ClientSession() as session:
        # A client giving up: its request times out and the connection closes
        with pytest.raises(asyncio.TimeoutError):
            await session.post(
                url,
                json=rpc("tools/call", {"name": "wait_forever"}),
                timeout=aiohttp.ClientTimeout(total=0.3),
            )
        assert started.is_set()
        await asyncio.wait_for(cleaned_up.wait(), 2)

        # The tool lock was released: the next call runs
        status, body = await post(
            session,
            server,
            rpc("tools/call", {"name": "add", "arguments": {"a": 1, "b": 2}}),
        )
        assert status == 200
        assert body["result"]["content"][0]["text"] == "3"


# -----------------------------------------------------------------------------
# The route at start, and the banner
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_route_exists_before_server_mcp_does(capsys):
    """Every app mounts the route at start; it answers 503 until the app
    creates server.mcp and turns it on."""
    server = new_server()
    await start(server)
    try:
        assert server._mcp is None
        assert server._mcp_endpoint_mounted is True
        async with aiohttp.ClientSession() as session:
            status, body = await post(session, server)
            assert status == 503
            assert body["error"]["message"] == DISABLED
            assert server._mcp is None

            mcp = server.mcp  # created once the server runs
            assert mcp.http.url == f"http://localhost:{server.port}/mcp"
            with pytest.raises(RuntimeError, match="started"):
                mcp.http.path = "/other"
            status, _ = await post(session, server)
            assert status == 503
            assert "MCP server available" not in capsys.readouterr().out

            mcp.enabled = True
            assert f"MCP server available at {mcp.http.url}" in capsys.readouterr().out
            status, body = await post(session, server)
            assert (status, body["result"]) == (200, {})
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_off_until_enabled_then_announced(capsys, caplog):
    """Declared but off: 503 and no banner; once running, the switch applies
    and the banner prints when access goes live, once."""
    server = new_server()
    mcp = server.mcp

    @mcp.tool
    def hello() -> str:
        """Say hi."""
        return "hi"

    with caplog.at_level(logging.INFO, logger="trame_server.mcp"):
        await start(server)
    try:
        assert f"{mcp.http.url} is mounted, but agent access is off" in caplog.text
        assert mcp.enabled is False
        assert "MCP server available" not in capsys.readouterr().out
        async with aiohttp.ClientSession() as session:
            status, _ = await post(session, server)
            assert status == 503

            mcp.enabled = True
            out = capsys.readouterr().out
            assert f"MCP server available at {mcp.http.url}" in out
            assert claude_command(mcp.name, mcp.http.url) in out
            assert codex_command(mcp.name, mcp.http.url) in out
            status, _ = await post(session, server)
            assert status == 200

            mcp.enabled = False
            mcp.enabled = True
            assert "MCP server available" not in capsys.readouterr().out  # once
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_enabled_before_start_is_announced_when_ready(capsys):
    server = new_server()
    mcp = server.mcp
    mcp.configure(name="viewer", enabled=True)
    mcp.http.token = "s3cret"
    assert "MCP server available" not in capsys.readouterr().out

    await start(server)
    try:
        out = capsys.readouterr().out
        assert out.count("MCP server available") == 1
        # a token the user set is shown as a placeholder
        assert claude_command("viewer", mcp.http.url, "<token>") in out
        assert "s3cret" not in out
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_the_banner_follows_the_connection_information(capsys):
    """Apps started in main mode print the connection information when ready;
    the banner follows it, once."""
    from trame_server.utils.server import print_informations  # noqa: PLC0415

    server = new_server()
    server.mcp.enabled = True
    server.controller.on_server_ready.add(lambda **_: print_informations(server))
    await start(server)
    try:
        out = capsys.readouterr().out
        assert out.count("MCP server available") == 1
        assert out.index("App running at:") < out.index("MCP server available")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_no_mcp_serves_no_endpoint(monkeypatch, capsys):
    monkeypatch.setenv("TRAME_ARGS", "--no-mcp")
    server = new_server()
    mcp = server.mcp
    mcp.enabled = True
    assert mcp.enabled_locked is True
    assert mcp.enabled is False

    await start(server)
    try:
        assert server._mcp_endpoint_mounted is False
        mcp.enabled = True  # a UI switch, once running: still off
        assert mcp.enabled is False
        assert "MCP server available" not in capsys.readouterr().out
        async with aiohttp.ClientSession() as session:
            # No MCP route: only trame's static files answer
            status, allow = await status_of(session, server, method="GET")
            assert status == 404
            status, allow = await status_of(session, server)
            assert status in (404, 405)
            assert "POST" not in allow
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_no_mcp_without_server_mcp(monkeypatch):
    monkeypatch.setenv("TRAME_ARGS", "--no-mcp")
    server = new_server()
    await start(server)
    try:
        assert server._mcp_endpoint_mounted is False
        async with aiohttp.ClientSession() as session:
            assert (await status_of(session, server, method="GET"))[0] == 404
        assert server.mcp.enabled_locked is True
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_the_http_transport_switched_at_runtime(capsys, caplog):
    """transports=[]: the route is there but answers 503 and no banner
    prints, while agents in the process reach what the app declares. Adding
    http later serves it, and the banner prints then."""
    server = new_server()
    mcp = server.mcp
    mcp.configure(enabled=True, transports=[])

    @mcp.tool
    def hello() -> str:
        """Say hi."""
        return "hi"

    with caplog.at_level(logging.INFO, logger="trame_server.mcp"):
        await start(server)
    try:
        assert server._mcp_endpoint_mounted is True
        assert "MCP server available" not in capsys.readouterr().out
        assert (
            f"{mcp.http.url} is mounted, but the HTTP transport is off" in caplog.text
        )
        response = await mcp.protocol.handle(rpc("tools/call", {"name": "hello"}))
        assert response["result"]["content"] == [{"type": "text", "text": "hi"}]
        async with aiohttp.ClientSession() as session:
            status, body = await post(session, server)
            assert status == 503
            assert body["error"]["message"] == (
                "The application turned its HTTP transport off"
            )

            mcp.transports = ["http"]
            assert f"MCP server available at {mcp.http.url}" in capsys.readouterr().out
            assert (await post(session, server))[0] == 200

            mcp.transports = []
            assert (await post(session, server))[0] == 503
            mcp.transports = ["http"]
            assert "MCP server available" not in capsys.readouterr().out  # once
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_no_transport_at_start_keeps_the_route(monkeypatch):
    """--mcp-transport none only sets the starting value."""
    monkeypatch.setenv("TRAME_ARGS", "--mcp-transport none")
    server = new_server()
    await start(server)
    try:
        assert server._mcp_endpoint_mounted is True
        mcp = server.mcp
        assert (mcp.transports, mcp.transports_locked) == ((), False)
        mcp.configure(enabled=True, transports=["http"])
        async with aiohttp.ClientSession() as session:
            assert (await post(session, server))[0] == 200
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("create", [False, True])
async def test_no_mcp_transport_serves_no_endpoint(monkeypatch, create):
    monkeypatch.setenv("TRAME_ARGS", "--no-mcp-transport")
    server = new_server()
    if create:
        server.mcp  # noqa: B018
    await start(server)
    try:
        assert server._mcp_endpoint_mounted is False
        mcp = server.mcp
        assert mcp.transports_locked is True
        async with aiohttp.ClientSession() as session:
            assert (await status_of(session, server, method="GET"))[0] == 404
        mcp.enabled = True  # agents in the process only
        response = await mcp.protocol.handle(rpc("tools/list"))
        assert "result" in response
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_a_path_set_before_start(capsys):
    server = new_server()
    mcp = server.mcp
    mcp.configure(enabled=True)
    mcp.http.configure(path="api/mcp")
    assert mcp.http.path == "/api/mcp"

    await start(server)
    try:
        assert mcp.http.url == f"http://localhost:{server.port}/api/mcp"
        assert mcp.http.url in capsys.readouterr().out
        async with aiohttp.ClientSession() as session:
            status, _ = await post(session, server, path="/api/mcp")
            assert status == 200
            status, allow = await status_of(session, server, path="/mcp")
            assert "POST" not in allow
            assert status != 200
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_a_component_does_not_turn_mcp_on(capsys):
    """A component declaring methods for agents serves nothing until the app
    turns agent access on; building it does not even create server.mcp."""

    class EndpointViewer(TrameComponent):
        @mcp_method
        def reset_camera(self) -> str:
            """Reset the camera."""
            return "reset"

    server = new_server()
    viewer = EndpointViewer(server)
    assert server._mcp is None
    await start(server)
    try:
        assert "MCP server available" not in capsys.readouterr().out
        async with aiohttp.ClientSession() as session:
            status, _ = await post(session, server, rpc("tools/list"))
            assert status == 503
    finally:
        await server.stop()
    del viewer


@pytest.mark.asyncio
async def test_token_generated_when_listening_beyond_localhost(capsys):
    server = new_server()
    mcp = server.mcp
    mcp.enabled = True
    assert mcp.http.token is None

    await start(server, host="0.0.0.0")
    try:
        assert mcp.http.token
        assert mcp.http.url == f"http://localhost:{server.port}/mcp"
        out = capsys.readouterr().out
        assert f"Bearer {mcp.http.token}" in out
        assert "token generated because the server listens beyond localhost" in out

        async with aiohttp.ClientSession() as session:
            status, _ = await post(session, server)
            assert status == 401
            status, _ = await post(
                session, server, headers={"Authorization": f"Bearer {mcp.http.token}"}
            )
            assert status == 200
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_a_token_set_after_one_was_generated_is_not_shown(capsys):
    server = new_server()
    mcp = server.mcp
    await start(server, host="0.0.0.0")
    try:
        assert mcp.http.token  # generated: the server listens beyond localhost
        mcp.http.token = "mine"
        mcp.enabled = True
        out = capsys.readouterr().out
        assert "MCP server available" in out
        assert "Bearer <token>" in out
        assert "mine" not in out
        assert "token generated" not in out
    finally:
        await server.stop()
