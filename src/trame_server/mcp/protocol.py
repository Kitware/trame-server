"""MCP JSON-RPC method dispatch (transport-independent).

Clients of both eras are served, as MCP 2026-07-28 lets a server do. A
request that names its protocol version in ``_meta`` comes from a client of
2026-07-28 or later: it carries everything needed to serve it, and its
result says so (``resultType``, the server's identity, caching hints). A
client that opens with ``initialize`` speaks an earlier revision and is
served as that revision says.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import logging
import re

from trame_server.mcp import call_log, progress
from trame_server.mcp.content import to_error_result, to_tool_result
from trame_server.mcp.schema import ToolError, ValidationError, bind_arguments

logger = logging.getLogger("trame_server.mcp")

__all__ = ["MCPProtocol"]

# 2026-07-28 and later: every request names its version and the client's
# capabilities in _meta, and there is no handshake
MODERN_VERSIONS = ("2026-07-28",)
# Earlier revisions open with an initialize handshake, which negotiates one
# of these (the first is preferred); still served for clients that have not
# moved on
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS

# Reserved _meta keys
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"

# The results that carry caching hints (2026-07-28)
CACHEABLE = frozenset(
    (
        "server/discover",
        "tools/list",
        "prompts/list",
        "resources/list",
        "resources/templates/list",
        "resources/read",
    )
)

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# MCP's own (2026-07-28)
HEADER_MISMATCH = -32020
UNSUPPORTED_VERSION = -32022
# The reply to a request the client cancelled (LSP's code; MCP defines none).
# The client ignores it, but an HTTP POST has to end with something.
REQUEST_CANCELLED = -32800


def _error(rpc_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": error}


def _result(rpc_id, payload):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}


async def _call(fn, arguments):
    value = fn(**arguments)
    if inspect.isawaitable(value):
        value = await value
    return value


def _meta(params):
    """A request's ``_meta``, or an empty dict."""
    meta = params.get("_meta") if isinstance(params, dict) else None
    return meta if isinstance(meta, dict) else {}


def request_version(message):
    """The protocol version a request names in its ``_meta``, as clients of
    2026-07-28 and later do; None for a client of an earlier revision."""
    return _meta(message.get("params")).get(VERSION_KEY)


def _caller(message, session):
    """Who is asking, for the call log: the start of an HTTP session id,
    else the name the client gives, kept to a few safe characters."""
    if isinstance(session, str):
        return session[:6]
    info = _meta(message.get("params")).get(CLIENT_INFO_KEY)
    name = info.get("name") if isinstance(info, dict) else None
    if not isinstance(name, str):
        return None
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:24] or None


def _reporter(params, notify):
    """The progress reporter of a request asking for progress, when its
    transport can notify; None otherwise."""
    token = _meta(params).get("progressToken")
    if notify is None or isinstance(token, bool) or not isinstance(token, (str, int)):
        return None

    async def send(fields):
        await notify(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progressToken": token, **fields},
            }
        )

    return progress.Reporter(send)


def check_request(message):
    """The error that a request naming its version gets before it is handled (an
    unsupported version, or missing client capabilities), or None. The HTTP
    endpoint answers these errors with 400."""
    rpc_id = message.get("id")
    version = request_version(message)
    if version not in MODERN_VERSIONS:
        hint = " (it opens with initialize)" if version in LEGACY_VERSIONS else ""
        return _error(
            rpc_id,
            UNSUPPORTED_VERSION,
            f"Unsupported protocol version: {version!r}{hint}",
            {"supported": list(PROTOCOL_VERSIONS), "requested": version},
        )
    if not isinstance(message["params"]["_meta"].get(CAPABILITIES_KEY), dict):
        return _error(rpc_id, INVALID_PARAMS, f"_meta must carry {CAPABILITIES_KEY}")
    return None


def _describe_failure(name, error):
    """Log a tool's exception, and return the text the agent reads. Expected
    failures are logged at DEBUG, the others as errors with their traceback."""
    if isinstance(error, (ValueError, LookupError, PermissionError)):
        # Expected, actionable failures (bad input, unknown target, ...)
        logger.debug("Tool %s failed: %s", name, error)
        if isinstance(error, (ToolError, PermissionError)):
            return str(error)
    else:
        logger.error("Tool %s raised", name, exc_info=error)
    return f"{type(error).__name__}: {error}"


class MCPProtocol:
    """Dispatches MCP JSON-RPC messages against an ``MCP`` instance's registries."""

    def __init__(self, mcp):
        self._mcp = mcp
        self._call_lock = asyncio.Lock()
        # (session, request id) -> task of a request still running, and the
        # tasks cancelled by the client -> its reason
        self._in_flight = {}
        self._cancelled = {}
        served = {
            "tools/list": self._on_tools_list,
            "tools/call": self._on_tools_call,
            "resources/list": self._on_resources_list,
            "resources/templates/list": self._on_resource_templates_list,
            "resources/read": self._on_resources_read,
            "prompts/list": self._on_prompts_list,
            "prompts/get": self._on_prompts_get,
        }
        self._modern_handlers = {"server/discover": self._on_discover, **served}
        self._legacy_handlers = {
            "initialize": self._on_initialize,
            "ping": self._on_ping,
            **served,
        }

    async def handle(self, message: dict, *, session=None, notify=None) -> dict | None:
        """Handle one JSON-RPC message. Returns a response dict, or None for
        notifications and responses, which expect no reply.

        ``session`` scopes request ids, so that ``notifications/cancelled`` only
        reaches the requests of the client that sent it. The HTTP endpoint passes
        the ``Mcp-Session-Id`` header of clients older than 2026-07-28, and an
        in-process client passes itself. A request the client cancels is answered
        with a ``REQUEST_CANCELLED`` error, which the client ignores.

        ``notify``, an async callable, sends the client a notification about this
        request before the response; the transport passes one when it can send
        notifications. With it, a request asking for progress (a
        ``progressToken`` in its ``_meta``) gets the progress its tool or method
        reports.
        """
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "Invalid JSON-RPC 2.0 message")

        method = message.get("method")
        rpc_id = message.get("id")

        if method is None:
            # A response from the client to a server request needs nothing more.
            return None
        if not isinstance(method, str):
            return _error(rpc_id, INVALID_REQUEST, "Invalid method")

        # The calls made while handling it know who asked (the call log)
        with call_log.request(_caller(message, session)):
            return await self._dispatch(message, method, rpc_id, session, notify)

    async def _dispatch(self, message, method, rpc_id, session, notify):
        if method.startswith("notifications/"):
            if method == "notifications/cancelled":
                params = message.get("params")
                if isinstance(params, dict):
                    self.cancel(
                        params.get("requestId"),
                        session=session,
                        reason=params.get("reason"),
                    )
            return None

        modern = request_version(message) is not None
        if modern:
            rejection = check_request(message)
            if rejection is not None:
                return rejection
        handler = self._handler(method, modern)
        if handler is None:
            return _error(rpc_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(rpc_id, INVALID_PARAMS, "params must be an object")

        reporter = _reporter(params, notify)
        try:
            with progress.reporting(reporter):
                payload = handler(params)
                if inspect.isawaitable(payload):
                    payload = await self._run_cancellable(payload, (session, rpc_id))
        except _RequestCancelled as e:
            return _error(rpc_id, REQUEST_CANCELLED, str(e))
        except _InvalidParams as e:
            return _error(rpc_id, INVALID_PARAMS, str(e))
        except PermissionError as e:
            return _error(rpc_id, INVALID_REQUEST, str(e))
        except Exception as e:
            logger.exception("Internal error handling %s", method)
            return _error(rpc_id, INTERNAL_ERROR, f"{type(e).__name__}: {e}")
        finally:
            if reporter is not None:
                await reporter.close()  # nothing is sent after the response

        if modern:
            payload = self._complete(method, payload)
        return _result(rpc_id, payload)

    def _handler(self, method, modern):
        handlers = self._modern_handlers if modern else self._legacy_handlers
        return handlers.get(method)

    def handles(self, message) -> bool:
        """Whether a request's method is served, in its client's revision."""
        return (
            self._handler(message.get("method"), request_version(message) is not None)
            is not None
        )

    def _complete(self, method, payload):
        """A result as 2026-07-28 shapes it."""
        result = {"resultType": "complete", **payload}
        result["_meta"] = {
            **(payload.get("_meta") or {}),
            SERVER_INFO_KEY: self._info(),
        }
        if method in CACHEABLE:
            # What it lists changes as the app runs, with no notification
            # sent, and describes one app's live state
            result["ttlMs"] = 0
            result["cacheScope"] = "private"
        return result

    def _info(self):
        from trame_server import __version__  # noqa: PLC0415

        return {"name": self._mcp.name, "version": __version__}

    # -------------------------------------------------------------------------
    # Cancellation
    # -------------------------------------------------------------------------

    def cancel(self, request_id, *, session=None, reason=None) -> bool:
        """Cancel the running request ``request_id`` of ``session``, as
        ``notifications/cancelled`` does. Returns whether one was running.

        The request's task is cancelled: its tool stops at its next
        ``await`` (a synchronous tool has finished before any cancel can
        arrive), releasing the call lock and flushing the state it changed.
        """
        try:
            task = self._in_flight.get((session, request_id))
        except TypeError:  # an unhashable id: no request has it
            return False
        if task is None or task.done():
            return False
        logger.info(
            "Request %r cancelled by the client: %s", request_id, reason or "no reason"
        )
        self._cancelled[task] = reason
        task.cancel()
        return True

    async def _run_cancellable(self, awaitable, key):
        """Await ``awaitable`` as a task that ``cancel(key)`` can stop."""
        task = asyncio.ensure_future(awaitable)
        try:
            registered = self._in_flight.setdefault(key, task) is task
        except TypeError:
            registered = False
        try:
            return await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            # Task.cancelling() is Python 3.11+; without it, assume not
            outer_cancelled = (
                current is not None and getattr(current, "cancelling", int)()
            )
            if task not in self._cancelled or outer_cancelled:
                raise  # cancelled from the outside, e.g. the client disconnected
            reason = self._cancelled[task]
            msg = f"Request cancelled: {reason}" if reason else "Request cancelled"
            raise _RequestCancelled(msg) from None
        finally:
            self._cancelled.pop(task, None)
            if registered and self._in_flight.get(key) is task:
                del self._in_flight[key]

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def _on_discover(self, _params):
        return {
            "supportedVersions": list(PROTOCOL_VERSIONS),
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "instructions": self._mcp._agent_instructions(),
        }

    def _on_initialize(self, params):
        """The handshake of clients before 2026-07-28."""
        requested = params.get("protocolVersion")
        version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
        payload = {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": self._info(),
        }
        payload["instructions"] = self._mcp._agent_instructions()
        return payload

    def _on_ping(self, _params):
        return {}

    # -------------------------------------------------------------------------
    # Tools
    # -------------------------------------------------------------------------

    def _on_tools_list(self, _params):
        tools = []
        for entry in self._mcp.list_tools():
            descriptor = {
                "name": entry.name,
                "description": entry.description,
                "inputSchema": self._mcp._input_schema(entry),
            }
            if entry.annotations:
                descriptor["annotations"] = entry.annotations
            tools.append(descriptor)
        return {"tools": tools}

    async def _on_tools_call(self, params):
        name = params.get("name")
        entry = self._mcp.get_tool(name) if isinstance(name, str) else None
        if entry is None:
            msg = f"Unknown tool: {name}"
            with call_log.logged("tool", str(name), params.get("arguments")):
                raise _InvalidParams(msg)

        try:
            value = await self._execute(entry, params.get("arguments"))
        except Exception as e:
            return to_error_result(_describe_failure(name, e))

        return to_tool_result(value, structured=self._mcp.structured_content)

    async def _execute(self, entry, arguments):
        """Run a tool entry. Access, permissions and arguments are checked first, then
        the call runs, one at a time unless it may run concurrently.

        Returns the tool's raw value; raises on failure.
        """
        with call_log.logged("tool", entry.name, arguments):
            self._mcp._check_enabled()
            self._mcp.permissions.require(*entry.requires, what=entry.name)
            try:
                arguments = bind_arguments(
                    entry.fn, arguments, self._mcp._input_schema(entry)
                )
            except ValidationError as e:
                msg = f"Invalid arguments for tool {entry.name}: {e}"
                raise ValidationError(msg) from None

            async with self.locked(entry.concurrent):
                # Ids given for object-typed parameters become objects here,
                # under the lock, where the graph is as earlier calls left it.
                arguments = self._mcp._objects.resolve_arguments(
                    entry.fn,
                    arguments,
                    read_only=bool((entry.annotations or {}).get("readOnlyHint")),
                )
                arguments = progress.inject(entry.fn, arguments)
                result = await self._call_flushing(entry.fn, arguments)
                if entry.input_schema is None:  # the app's own tool
                    result = self._mcp._objects.encode_tool_result(result)
            return result

    @contextlib.asynccontextmanager
    async def locked(self, concurrent=False):
        """Hold the call lock for the block, so that agent calls run one at a time.
        Nothing is held when the call is ``concurrent``, or when every call may be
        (``concurrent_calls``).

        ``object_call`` runs unlocked and takes the lock here itself, so the
        called method's own ``concurrent`` option decides.
        """
        if not (concurrent or self._mcp.concurrent_calls):
            async with self._call_lock:
                yield
        else:
            yield

    async def _call_flushing(self, fn, arguments):
        # trame pushes state changes and runs @state.change reactions on a
        # flush, which an HTTP request never triggers by itself: without one,
        # what a tool assigns would wait for some unrelated flush.
        with self._mcp.server.state:
            return await _call(fn, arguments)

    # -------------------------------------------------------------------------
    # Resources
    # -------------------------------------------------------------------------

    def _on_resources_list(self, _params):
        return {
            "resources": [
                {
                    "uri": entry.uri,
                    "name": entry.name,
                    **({"description": entry.description} if entry.description else {}),
                    **({"mimeType": entry.mime_type} if entry.mime_type else {}),
                }
                for entry in self._mcp.list_resources()
            ]
        }

    def _on_resource_templates_list(self, _params):
        return {"resourceTemplates": []}

    async def _on_resources_read(self, params):
        uri = params.get("uri")
        entry = self._mcp.get_resource(uri) if isinstance(uri, str) else None
        if entry is None:
            msg = f"Unknown resource: {uri}"
            with call_log.logged("resource", str(uri)):
                raise _InvalidParams(msg)

        with call_log.logged("resource", entry.uri):
            self._mcp._check_enabled()
            value = await _call(entry.fn, {})
        if isinstance(value, bytes):
            content = {
                "uri": uri,
                "mimeType": entry.mime_type or "application/octet-stream",
                "blob": base64.b64encode(value).decode("ascii"),
            }
        else:
            if not isinstance(value, str):
                value = json.dumps(value)
            content = {
                "uri": uri,
                "mimeType": entry.mime_type or "text/plain",
                "text": value,
            }
        return {"contents": [content]}

    # -------------------------------------------------------------------------
    # Prompts
    # -------------------------------------------------------------------------

    def _on_prompts_list(self, _params):
        return {
            "prompts": [
                {
                    "name": entry.name,
                    **({"description": entry.description} if entry.description else {}),
                    "arguments": entry.arguments,
                }
                for entry in self._mcp.list_prompts()
            ]
        }

    async def _on_prompts_get(self, params):
        name = params.get("name")
        entry = self._mcp.get_prompt(name) if isinstance(name, str) else None
        if entry is None:
            msg = f"Unknown prompt: {name}"
            with call_log.logged("prompt", str(name), params.get("arguments")):
                raise _InvalidParams(msg)

        arguments = params.get("arguments") or {}
        with call_log.logged("prompt", name, arguments):
            self._mcp._check_enabled()
            try:
                inspect.signature(entry.fn).bind(**arguments)
            except TypeError as e:
                msg = f"Invalid arguments for prompt {name}: {e}"
                raise _InvalidParams(msg) from None

            value = await _call(entry.fn, arguments)
        if isinstance(value, str):
            messages = [{"role": "user", "content": {"type": "text", "text": value}}]
        else:
            messages = value
        return {
            **({"description": entry.description} if entry.description else {}),
            "messages": messages,
        }


class _InvalidParams(ValueError):
    pass


class _RequestCancelled(Exception):
    pass
