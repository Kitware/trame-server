"""Agent access to trame applications through MCP (Model Context Protocol).

``server.mcp`` is the MCP server of a trame server: it serves the tools,
resources and prompts an application declares, and the objects it exposes,
to agents in other processes through its transports (HTTP, on the same port
as the application) and to agents inside it (``server.mcp.client()``). See
:class:`trame_server.mcp.core.MCP`.
"""

from trame_common.obj.mcp import Progress

from trame_server.mcp.client import MCPClient, MCPError
from trame_server.mcp.content import Image
from trame_server.mcp.core import MCP, MCPDisabledError
from trame_server.mcp.endpoint import HTTPTransport, claude_command, codex_command
from trame_server.mcp.permissions import PermissionDeniedError
from trame_server.mcp.schema import ToolError, ValidationError

__all__ = [
    "MCP",
    "HTTPTransport",
    "Image",
    "MCPClient",
    "MCPDisabledError",
    "MCPError",
    "PermissionDeniedError",
    "Progress",
    "ToolError",
    "ValidationError",
    "claude_command",
    "codex_command",
]
