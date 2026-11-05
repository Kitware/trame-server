"""Agents inside the application's process: ``server.mcp.client()``.

An in-process client needs no transport. It hands the protocol the
requests an agent connected over a transport would send (MCP 2026-07-28),
so what it sees and may do is the same: ``mcp.enabled``, permissions,
argument validation, calls one at a time and the call log all apply.
"""

from __future__ import annotations

import inspect
import itertools
import logging

from trame_server.mcp.protocol import (
    CAPABILITIES_KEY,
    CLIENT_INFO_KEY,
    MODERN_VERSIONS,
    VERSION_KEY,
)

logger = logging.getLogger("trame_server.mcp")

__all__ = ["MCPClient", "MCPError"]

# What a 2026-07-28 result carries for transports, not for the caller
ENVELOPE = ("resultType", "_meta", "ttlMs", "cacheScope")


class MCPError(Exception):
    """Raised for a request the server cannot serve at all, such as a call to an
    unknown tool. It carries the JSON-RPC error's ``code``, ``message`` and
    ``data``. A tool that fails still returns a result, with ``isError`` set."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class MCPClient:
    """A client for an agent inside the application's process, returned by
    ``server.mcp.client()``. It lists what agents see and makes the calls
    they make.

    Results are the dicts MCP defines: a tool's result holds its ``content``,
    and ``isError`` when the tool failed, which an agent loop hands back to
    its model. Requests the server cannot serve raise :class:`MCPError`.
    Cancelling the task that awaits a call cancels the call.
    """

    def __init__(self, mcp, name="in-process"):
        self._mcp = mcp
        self._name = name
        self._ids = itertools.count(1)

    @property
    def name(self):
        """The name this client gives the server, shown in the call log."""
        return self._name

    @property
    def instructions(self):
        """What agents receive when they connect: the application's text,
        then the generated overview of what it exposes."""
        return self._mcp._agent_instructions()

    async def list_tools(self) -> list[dict]:
        """The tools agents may call, each with its ``name``,
        ``description``, ``inputSchema`` and ``annotations``."""
        return (await self._request("tools/list"))["tools"]

    async def call_tool(self, name, arguments=None, *, on_progress=None) -> dict:
        """Call a tool and return its result: ``content``, and ``isError`` when the
        tool failed.

        With ``on_progress``, the call asks for the progress that its tool or
        method reports, and each report calls ``on_progress(value, total,
        message)``, which may be async. These calls run on the event loop, before
        the call returns.
        """
        params = {"name": name, "arguments": arguments or {}}
        if on_progress is None:
            return await self._request("tools/call", params)

        async def notify(notification):
            fields = notification["params"]
            try:
                done = on_progress(
                    fields["progress"], fields.get("total"), fields.get("message")
                )
                if inspect.isawaitable(done):
                    await done
            except Exception:  # the call goes on without it
                logger.exception("on_progress failed")

        return await self._request("tools/call", params, notify=notify)

    async def list_resources(self) -> list[dict]:
        """The resources agents may read, each with its ``uri`` and
        ``name``."""
        return (await self._request("resources/list"))["resources"]

    async def read_resource(self, uri) -> list[dict]:
        """Read a resource. Returns its contents, each with its ``uri``,
        ``mimeType`` and ``text`` (or ``blob``, base64-encoded bytes)."""
        return (await self._request("resources/read", {"uri": uri}))["contents"]

    async def list_prompts(self) -> list[dict]:
        """The prompts agents may get, each with its ``name`` and
        ``arguments``."""
        return (await self._request("prompts/list"))["prompts"]

    async def get_prompt(self, name, arguments=None) -> dict:
        """Get a prompt. Returns its ``messages`` (and ``description``)."""
        return await self._request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )

    async def _request(self, method, params=None, notify=None):
        from trame_server import __version__  # noqa: PLC0415

        rpc_id = next(self._ids)
        meta = {
            VERSION_KEY: MODERN_VERSIONS[0],
            CAPABILITIES_KEY: {},
            CLIENT_INFO_KEY: {"name": self._name, "version": __version__},
        }
        if notify is not None:
            meta["progressToken"] = rpc_id  # unique among its running requests
        message = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": {**(params or {}), "_meta": meta},
        }
        # The client itself scopes its request ids, as a session would
        response = await self._mcp.protocol.handle(message, session=self, notify=notify)
        if "error" in response:
            error = response["error"]
            raise MCPError(error["code"], error["message"], error.get("data"))
        return {k: v for k, v in response["result"].items() if k not in ENVELOPE}
