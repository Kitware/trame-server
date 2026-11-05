"""The HTTP transport: the endpoint agents connect to (``server.mcp.http``,
``/mcp`` by default), on the trame web server's port.

:class:`HTTPTransport` holds its options. :class:`MCPEndpoint` handles
requests without depending on a web server: a host hands it an
:class:`HTTPRequest` and sends back the :class:`HTTPResponse`.
:func:`mount` adapts it to aiohttp, trame's default web server. The server
mounts it when it starts, in every app unless launched with ``--no-mcp``
or ``--no-mcp-transport``. The route exists from the start because
aiohttp freezes its routes then, while agent access and the transport can
be turned on later. Until ``server.mcp`` exists, is enabled and serves
HTTP, the endpoint answers 503.

Every request goes through, in order:

1. ``Origin`` check: browsers always send it on cross-site requests, so a
   page from another site can never drive the tools (CSRF).
2. Bearer token, when one is set. Without a token, the ``Host`` must be a
   loopback address, which defeats DNS rebinding.
3. ``mcp.enabled``, then ``"http"`` in ``mcp.transports``: 503 while
   agent access or the transport is off.
4. ``Content-Type: application/json``, so browsers cannot send a request
   without a CORS preflight, which this endpoint never grants.

The transport is streamable HTTP with JSON responses, for clients of both
eras (see :mod:`trame_server.mcp.protocol`):

- A request naming its protocol version in ``_meta`` (2026-07-28 and
  later) is served statelessly. Its ``MCP-Protocol-Version``,
  ``Mcp-Method`` and ``Mcp-Name`` headers must match its body, else 400
  (``HeaderMismatch``). An unsupported version or missing metadata gets
  400, and an unknown method 404. No session id is given or read.
- A client that opens with ``initialize`` is served as earlier revisions
  say: the response carries an ``Mcp-Session-Id`` that only scopes request
  ids for ``notifications/cancelled``.

Either way, a request whose client disconnects is cancelled. A request
that asks for progress gets its response as Server-Sent Events once its
first notification goes out: the notifications, then the response.
Without a notification, the response stays plain JSON.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import ipaddress
import json
import logging
import secrets
import shlex
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from trame_server.mcp.protocol import (
    HEADER_MISMATCH,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MODERN_VERSIONS,
    PARSE_ERROR,
    check_request,
    request_version,
)

logger = logging.getLogger("trame_server.mcp")

__all__ = [
    "HTTPRequest",
    "HTTPResponse",
    "HTTPTransport",
    "MCPEndpoint",
    "claude_command",
    "codex_command",
    "is_loopback",
    "mount",
]

WILDCARD_HOSTS = ("", "0.0.0.0", "::")
SERVER_ERROR = -32000
SESSION_HEADER = "Mcp-Session-Id"
# Seconds between checks that the client of a running request is still there
DISCONNECT_POLL = 0.5
# The body field each method mirrors into Mcp-Name (2026-07-28)
NAMED_BY = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
# How a header value outside plain ASCII is sent (2026-07-28)
BASE64_PREFIX, BASE64_SUFFIX = "=?base64?", "?="
# A response sent as Server-Sent Events (X-Accel-Buffering: proxies pass
# each event on at once)
EVENT_STREAM_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def is_loopback(host) -> bool:
    """True for ``localhost`` names and loopback IP literals."""
    if not host:
        return False
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def claude_command(name, url, token=None):
    """A Claude Code command starting a session with this server added for
    that session only (``--mcp-config``), next to the user's own MCP
    servers."""
    server = {"type": "http", "url": url}
    if token:
        server["headers"] = {"Authorization": f"Bearer {token}"}
    config = json.dumps({"mcpServers": {name: server}}, separators=(",", ":"))
    return f"claude --mcp-config {shlex.quote(config)}"


def codex_command(name, url, token=None):
    """A Codex command starting a session with this server added for that
    session only: each ``-c`` overrides one config value (TOML) for the
    run, here the server's entry under ``mcp_servers``."""
    overrides = [f"mcp_servers.{name}.url={json.dumps(url)}"]
    if token:
        header = json.dumps(f"Bearer {token}")
        overrides.append(f"mcp_servers.{name}.http_headers={{Authorization={header}}}")
    return " ".join(["codex", *(f"-c {shlex.quote(o)}" for o in overrides)])


class HTTPTransport:
    """The options of the HTTP transport (``server.mcp.http``), which is served
    while ``mcp.transports`` includes ``"http"``, as it does by default.

    Every option is a settable attribute, and ``configure()`` sets several at
    once. ``path`` is fixed once the server has started; the other options
    can change at any time.
    """

    def __init__(self, mcp):
        self._mcp = mcp
        self._path = "/mcp"
        self._token = None
        self._token_generated = False
        self._allowed_origins = ()
        self._announced = False

    def configure(self, *, path=None, token=None, allowed_origins=None):
        """Set several options at once; an option left as None is unchanged. This
        is the same as assigning the attributes one by one."""
        options = {"path": path, "token": token, "allowed_origins": allowed_origins}
        for key, value in options.items():
            if value is not None:
                setattr(self, key, value)

    @property
    def path(self):
        """The endpoint's path on the trame web server. It is fixed once the server
        has started."""
        return self._path

    @path.setter
    def path(self, value):
        if self._mcp._started:
            msg = "MCP 'path' cannot change once the server has started"
            raise RuntimeError(msg)
        self._path = value if value.startswith("/") else f"/{value}"

    @property
    def token(self):
        """The bearer token the endpoint requires, or None.

        ``--mcp-http-token`` or ``TRAME_MCP_HTTP_TOKEN`` take precedence over values
        the application sets before the server starts. When the server listens
        beyond loopback and no token is set, one is generated at startup and printed
        with the connection instructions.
        """
        return self._token

    @token.setter
    def token(self, value):
        if self._mcp._launch_overrides("token"):
            return
        self._token = str(value) if value else None
        self._token_generated = False

    @property
    def allowed_origins(self):
        """Extra browser origins (``"https://host:port"``) allowed to call the
        endpoint. Loopback origins and the endpoint's own origin are always
        allowed; requests without an ``Origin`` header are unaffected."""
        return self._allowed_origins

    @allowed_origins.setter
    def allowed_origins(self, value):
        if isinstance(value, str):
            value = (value,)
        self._allowed_origins = tuple(o.rstrip("/") for o in value)

    @property
    def url(self):
        """The endpoint's URL, as agents on this machine reach it."""
        host = self._bind_host
        if not host or host in WILDCARD_HOSTS:
            host = "localhost"
        elif ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{self._mcp.server.port}{self._path}"

    @property
    def _bind_host(self):
        options = getattr(self._mcp.server, "_server_options", None)
        return getattr(options, "host", None)

    @property
    def _mounted(self):
        return self._mcp.server._mcp_endpoint_mounted

    @property
    def _serving(self):
        return self._mounted and "http" in self._mcp.transports

    @property
    def _live(self):
        return self._mcp.enabled and self._serving

    def _start(self):
        if self._token is None and not is_loopback(self._bind_host):
            # Listening beyond this machine: never serve an unauthenticated
            # automation API to the network.
            self._token = generate_token()
            self._token_generated = True

    def _on_ready(self):
        if self._live:
            self._announce()
        elif not self._mcp.enabled and self._mounted:
            logger.info(
                "%s is mounted, but agent access is off (set mcp.enabled = True or "
                "launch with --mcp)",
                self.url,
            )
        elif self._mounted:
            logger.info(
                "%s is mounted, but the HTTP transport is off (add it to "
                "mcp.transports)",
                self.url,
            )

    def _announce(self):
        """Print how to connect, the first time access is live."""
        if self._announced or not (self._mcp._ready and self._live):
            return
        self._announced = True
        from trame_server.utils.server import print_mcp_informations  # noqa: PLC0415

        print_mcp_informations(self._mcp.server)


@dataclass
class HTTPRequest:
    """What the endpoint needs of a request."""

    method: str
    headers: Mapping[str, str]  # lower-case names
    host: str | None  # the host name the client addressed, without the port
    authority: str | None  # the ``Host`` header as sent: host[:port]
    read: Callable[[], Awaitable[bytes]]
    disconnected: Callable[[], bool] = lambda: False
    # Starts the response as a stream with these headers; returns an async
    # function writing text to it. None: the host can't stream responses.
    open_stream: (
        Callable[[dict], Awaitable[Callable[[str], Awaitable[None]]]] | None
    ) = None

    @property
    def content_type(self):
        value = self.headers.get("content-type") or ""
        return value.split(";")[0].strip().lower()


@dataclass
class HTTPResponse:
    status: int
    body: dict | None = None
    headers: dict = field(default_factory=dict)
    reason: str | None = None
    streamed: bool = False  # sent already, on the stream ``open_stream`` began


class _EventStream:
    """A request's response as Server-Sent Events, begun by the first
    notification: the notifications, then the response."""

    def __init__(self, request):
        self._request = request
        self._write = None

    @property
    def begun(self):
        return self._write is not None

    async def send(self, message):
        if self._write is None:
            self._write = await self._request.open_stream(EVENT_STREAM_HEADERS)
        data = json.dumps(message, separators=(",", ":"))
        await self._write(f"event: message\ndata: {data}\n\n")


def _event_stream(request):
    """The event stream that a request's first notification starts, or None when
    its host or its client cannot use one."""
    accept = request.headers.get("accept") or ""
    if request.open_stream is None or "text/event-stream" not in accept:
        return None
    return _EventStream(request)


def _error_response(status, message, headers=None, code=SERVER_ERROR, rpc_id=None):
    body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
    return HTTPResponse(status, body, headers or {})


def _decoded(value):
    """A header value, decoded when sent in the Base64 form."""
    if value.startswith(BASE64_PREFIX) and value.endswith(BASE64_SUFFIX):
        encoded = value[len(BASE64_PREFIX) : -len(BASE64_SUFFIX)]
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except ValueError:  # binascii.Error, UnicodeDecodeError
            return None
    return value


def _header_mismatch(headers, message):
    """What is wrong with the headers a 2026-07-28 request mirrors from its
    body, or None."""
    method = message.get("method")
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    expected = [
        ("MCP-Protocol-Version", request_version(message)),
        ("Mcp-Method", method),
    ]
    if method in NAMED_BY:
        expected.append(("Mcp-Name", params.get(NAMED_BY[method])))
    for name, value in expected:
        sent = headers.get(name.lower())
        if sent is None:
            return f"Header mismatch: the {name} header is missing"
        if name == "Mcp-Name":
            sent = _decoded(sent)
        if sent != value:
            return (
                f"Header mismatch: {name} header value {sent!r} does not match "
                f"body value {value!r}"
            )
    return None


async def _cancel_on_disconnect(request, task):
    """Cancel ``task`` if the client of ``request`` disconnects before it ends, and
    return whether it did. aiohttp keeps a handler running after its client is
    gone, and exposes no callback for it once the body is read."""
    while not task.done():
        await asyncio.sleep(DISCONNECT_POLL)
        if request.disconnected():
            task.cancel()
            return True
    return False


class MCPEndpoint:
    """Serves MCP over HTTP for a trame server (its root), whether or not
    ``server.mcp`` exists yet."""

    def __init__(self, server):
        self._server = server.root_server

    @property
    def _mcp(self):
        return self._server._mcp

    def _origin_allowed(self, origin, request):
        mcp = self._mcp
        if mcp is not None and origin in mcp.http.allowed_origins:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if not parsed.hostname:  # e.g. "null" from sandboxed frames / file://
            return False
        return is_loopback(parsed.hostname) or parsed.netloc == request.authority

    def _check(self, request):
        origin = request.headers.get("origin")
        if origin is not None and not self._origin_allowed(origin, request):
            logger.warning("Rejected an MCP request from origin %r", origin)
            return _error_response(403, "Origin not allowed")

        mcp = self._mcp
        token = mcp.http.token if mcp is not None else None
        if token:
            scheme, _, credentials = request.headers.get("authorization", "").partition(
                " "
            )
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                credentials.strip().encode(), token.encode()
            ):
                return _error_response(
                    401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"}
                )
        elif not is_loopback(request.host):
            return _error_response(
                403,
                "Host not allowed: set a token (mcp.http.token, --mcp-http-token or "
                "TRAME_MCP_HTTP_TOKEN) to serve MCP under a non-loopback host name",
            )

        if mcp is None or not mcp.enabled:
            return _error_response(
                503, "MCP access is currently disabled by the application"
            )
        if "http" not in mcp.transports:
            return _error_response(503, "The application turned its HTTP transport off")

        if request.content_type != "application/json":
            return _error_response(415, "Content-Type must be application/json")

        return None

    def _check_modern(self, request, message):
        """The 400 or 404 response that a request from a 2026-07-28 client gets, or
        None. Such a request names its version in its body, or its headers say it
        should."""
        if (
            request_version(message) is None
            and request.headers.get("mcp-protocol-version") not in MODERN_VERSIONS
        ):
            return None
        rpc_id = message.get("id")
        mismatch = _header_mismatch(request.headers, message)
        if mismatch is not None:
            return _error_response(400, mismatch, code=HEADER_MISMATCH, rpc_id=rpc_id)
        error = check_request(message)
        if error is not None:
            return HTTPResponse(400, error)
        if not self._mcp.protocol.handles(message):
            return _error_response(
                404,
                f"Method not found: {message.get('method')}",
                code=METHOD_NOT_FOUND,
                rpc_id=rpc_id,
            )
        return None

    async def post(self, request: HTTPRequest) -> HTTPResponse:
        rejection = self._check(request)
        if rejection is not None:
            return rejection

        try:
            message = json.loads(await request.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error_response(400, "Parse error", code=PARSE_ERROR)

        if isinstance(message, list):
            return _error_response(
                400, "JSON-RPC batching is not supported", code=INVALID_REQUEST
            )

        protocol = self._mcp.protocol
        is_request = (
            isinstance(message, dict) and "method" in message and "id" in message
        )
        session = None
        if is_request and (rejection := self._check_modern(request, message)):
            return rejection
        if not isinstance(message, dict) or request_version(message) is None:
            # Before 2026-07-28 only: a session scoping cancellation
            session = request.headers.get(SESSION_HEADER.lower())
        stream = _event_stream(request) if is_request else None
        if is_request:
            notify = stream.send if stream is not None else None
            handling = asyncio.ensure_future(
                protocol.handle(message, session=session, notify=notify)
            )
            watching = asyncio.ensure_future(_cancel_on_disconnect(request, handling))
            try:
                response = await handling
            except asyncio.CancelledError:
                if not (
                    watching.done() and not watching.cancelled() and watching.result()
                ):
                    raise
                logger.info(
                    "MCP client disconnected, cancelled %s request %r",
                    message.get("method"),
                    message.get("id"),
                )
                # Never delivered; for the access log, as nginx does
                begun = stream is not None and stream.begun
                return HTTPResponse(499, reason="Client Closed Request", streamed=begun)
            finally:
                watching.cancel()
        else:
            response = await protocol.handle(message, session=session)
        if response is None:
            # Notification or client response: acknowledge without a body
            return HTTPResponse(202)
        if stream is not None and stream.begun:
            await stream.send(response)
            return HTTPResponse(200, streamed=True)

        headers = {}
        if is_request and message["method"] == "initialize" and "result" in response:
            headers[SESSION_HEADER] = secrets.token_urlsafe(24)
        return HTTPResponse(200, response, headers)

    @staticmethod
    def unsupported(_request=None) -> HTTPResponse:
        # Stateless server: no SSE stream to offer (GET), no session to end (DELETE)
        return HTTPResponse(405, headers={"Allow": "POST"})


# -----------------------------------------------------------------------------
# aiohttp
# -----------------------------------------------------------------------------


def _from_aiohttp(request, open_stream=None):
    def disconnected():
        transport = request.transport
        return transport is None or transport.is_closing()

    return HTTPRequest(
        method=request.method,
        headers={k.lower(): v for k, v in request.headers.items()},
        host=request.url.host,
        authority=request.host,
        read=request.read,
        disconnected=disconnected,
        open_stream=open_stream,
    )


def _to_aiohttp(response):
    from aiohttp import web  # noqa: PLC0415

    if response.body is None:
        return web.Response(
            status=response.status, headers=response.headers, reason=response.reason
        )
    return web.json_response(
        response.body, status=response.status, headers=response.headers
    )


def aiohttp_routes(endpoint, path):
    """The aiohttp routes serving ``endpoint`` at ``path``."""
    from aiohttp import web  # noqa: PLC0415

    async def post(request):
        streams = []

        async def open_stream(headers):
            stream = web.StreamResponse(status=200, headers=headers)
            await stream.prepare(request)
            streams.append(stream)

            async def write(text):
                await stream.write(text.encode())

            return write

        response = await endpoint.post(_from_aiohttp(request, open_stream))
        if not response.streamed:
            return _to_aiohttp(response)
        (stream,) = streams
        with contextlib.suppress(ConnectionError):  # the client may be gone
            await stream.write_eof()
        return stream

    async def other(_request):
        return _to_aiohttp(endpoint.unsupported())

    return [web.post(path, post), web.get(path, other), web.delete(path, other)]


def mount(server, wslink_server):
    """Mount the endpoint of ``server`` on the web server wslink started, when it is
    aiohttp's, and return whether it did. Other hosts can serve
    :class:`MCPEndpoint` themselves."""
    from aiohttp import web  # noqa: PLC0415 (wslink depends on aiohttp)

    app = getattr(wslink_server, "app", None)
    mcp = server._mcp
    if not isinstance(app, web.Application):
        # Only worth mentioning to an app that uses agents
        log = logger.info if mcp is not None else logger.debug
        log(
            "The MCP endpoint is not mounted: this web server is not aiohttp; "
            "serve trame_server.mcp.endpoint.MCPEndpoint yourself"
        )
        return False

    path = mcp.http.path if mcp is not None else "/mcp"
    app.add_routes(aiohttp_routes(MCPEndpoint(server), path))
    return True


def generate_token():
    return secrets.token_urlsafe(32)
