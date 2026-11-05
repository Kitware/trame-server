"""Serve the MCP endpoint on aiohttp, wslink's default web server.

The endpoint lives in :mod:`trame_server.mcp.endpoint.core`: this only turns
aiohttp requests into an :class:`~trame_server.mcp.endpoint.core.HTTPRequest`,
and the :class:`~trame_server.mcp.endpoint.core.HTTPResponse` back into an
aiohttp response, streamed when it is Server-Sent Events.
"""

from __future__ import annotations

import contextlib
import logging

from aiohttp import web

from trame_server.mcp.endpoint.core import HTTPRequest, MCPEndpoint

logger = logging.getLogger("trame_server.mcp")

__all__ = ["mount", "routes"]


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
    if response.body is None:
        return web.Response(
            status=response.status, headers=response.headers, reason=response.reason
        )
    return web.json_response(
        response.body, status=response.status, headers=response.headers
    )


def routes(endpoint, path):
    """The aiohttp routes serving ``endpoint`` (an :class:`MCPEndpoint`) at
    ``path``."""

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
    aiohttp's, and return whether it did. The ``generic``, ``jupyter`` and
    ``tornado`` backends give trame no web server to mount it on."""
    app = getattr(wslink_server, "app", None)
    mcp = server._mcp
    if not isinstance(app, web.Application):
        # Only worth mentioning to an app that uses agents
        log = logger.info if mcp is not None else logger.debug
        log(
            "The MCP endpoint is not mounted: this web server is not aiohttp. "
            "Agents in the process can use server.mcp.client(), and the host can "
            "serve trame_server.mcp.endpoint.MCPEndpoint"
        )
        return False

    path = mcp.http.path if mcp is not None else "/mcp"
    app.add_routes(routes(MCPEndpoint(server), path))
    return True
