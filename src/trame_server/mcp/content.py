"""Coercion of Python return values into MCP tool-result content."""

from __future__ import annotations

import base64
import json
from pathlib import Path

__all__ = [
    "Image",
    "to_tool_result",
]


class Image:
    """An image that a tool returns.

    .. code-block:: python

        @mcp.tool
        def screenshot() -> Image:
            return Image(png_bytes, mime_type="image/png")
    """

    def __init__(self, data: bytes, mime_type: str = "image/png"):
        self.data = data
        self.mime_type = mime_type

    @classmethod
    def from_file(cls, path, mime_type=None):
        path = Path(path)
        if mime_type is None:
            ext = path.suffix.lower().lstrip(".")
            mime_type = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
        return cls(path.read_bytes(), mime_type=mime_type)

    def to_content(self):
        return {
            "type": "image",
            "data": base64.b64encode(self.data).decode("ascii"),
            "mimeType": self.mime_type,
        }


def _default_encoder(value):
    if isinstance(value, Image):
        return f"<image {value.mime_type}>"
    return repr(value)


def to_tool_result(value, structured=False) -> dict:
    """Convert a tool's return value into an MCP ``tools/call`` result.

    Anything but text and images becomes compact JSON text. That includes None,
    which becomes ``null`` rather than an empty reply that would leave the agent
    guessing. With ``structured``, a dict is also sent as ``structuredContent``.
    Clients that show both then put the same value in the agent's context twice
    (see ``MCP.structured_content``)."""
    if isinstance(value, Image):
        return {"content": [value.to_content()]}

    if isinstance(value, str):
        return {"content": [{"type": "text", "text": value}]}

    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(v, (Image, str)) for v in value)
    ):
        return {
            "content": [
                v.to_content() if isinstance(v, Image) else {"type": "text", "text": v}
                for v in value
            ]
        }

    text = json.dumps(
        value, default=_default_encoder, separators=(",", ":"), ensure_ascii=False
    )
    result = {"content": [{"type": "text", "text": text}]}
    if structured and isinstance(value, dict):
        result["structuredContent"] = value
    return result


def to_error_result(message: str) -> dict:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
