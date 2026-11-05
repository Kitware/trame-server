"""The HTTP transport: the endpoint agents connect to (``server.mcp.http``,
``/mcp`` by default).

- :mod:`~trame_server.mcp.endpoint.core` is the endpoint, independent of any
  web server: :class:`MCPEndpoint` takes an :class:`HTTPRequest` and returns
  an :class:`HTTPResponse`. :class:`HTTPTransport` holds its options.
- :mod:`~trame_server.mcp.endpoint.aiohttp` serves it on aiohttp, trame's
  default web server, where the server mounts it when it starts.

The other wslink backends (``generic``, ``jupyter``, ``tornado``) give trame
no web server to mount it on. The host that owns the HTTP server can route
requests to ``MCPEndpoint(server)`` itself.
"""

from trame_server.mcp.endpoint.core import (
    HTTPRequest,
    HTTPResponse,
    HTTPTransport,
    MCPEndpoint,
    claude_command,
    codex_command,
    is_loopback,
)

__all__ = [
    "HTTPRequest",
    "HTTPResponse",
    "HTTPTransport",
    "MCPEndpoint",
    "claude_command",
    "codex_command",
    "is_loopback",
]
