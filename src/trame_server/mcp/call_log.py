"""The log of what agents call (``--mcp-log``).

Every tool call, resource read and prompt is logged once, when it ends, at
INFO on this module's logger: what was called, with its arguments
shortened, how it ended and how long it took. ``--mcp-log`` or
``TRAME_MCP_LOG`` set the ``trame_server.mcp`` loggers to INFO; where the
lines go is up to the application's logging configuration, as for any
other library.

``MCPProtocol.handle`` records who is asking in a context variable, which
follows the request into the task that runs it. The caller is the start of
the HTTP session id when there is one, else the name the client gives
(``clientInfo``), which is how in-process clients and clients of MCP
2026-07-28 are named.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import time

from trame_server.mcp.permissions import PermissionDeniedError

__all__ = ["logged", "request", "shorten"]

logger = logging.getLogger(__name__)

# How much of an argument a line shows
MAX_STRING = 60
MAX_ITEMS = 8
MAX_DEPTH = 3
MAX_WHAT = 300
MAX_ERROR = 200

_session = contextvars.ContextVar("trame_mcp_session", default="-")


@contextlib.contextmanager
def request(caller):
    """Mark the block as handling a request from ``caller`` (None when unknown),
    so that the calls made in it are logged under that name."""
    token = _session.set(caller or "-")
    try:
        yield
    finally:
        _session.reset(token)


def shorten(value, depth=0) -> str:
    """``value`` as compact JSON-like text: bare keys, long strings replaced
    by their length, long lists and dicts cut, deep nesting elided."""
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            return f"<str {len(value)} chars>"
        return json.dumps(value)
    if isinstance(value, dict):
        if depth >= MAX_DEPTH:
            return "{...}"
        items = [
            f"{k}: {shorten(v, depth + 1)}" for k, v in list(value.items())[:MAX_ITEMS]
        ]
        if len(value) > MAX_ITEMS:
            items.append(f"+{len(value) - MAX_ITEMS}")
        return "{" + ", ".join(items) + "}"
    if isinstance(value, (list, tuple)):
        if depth >= MAX_DEPTH:
            return "[...]"
        items = [shorten(v, depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"+{len(value) - MAX_ITEMS}")
        return "[" + ", ".join(items) + "]"
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
    return f"<{type(value).__name__}>"


def _describe_error(error) -> str:
    text = str(error).strip()
    first = text.splitlines()[0] if text else ""
    if not isinstance(error, (ValueError, LookupError, PermissionError)):
        first = f"{type(error).__name__}: {first}" if first else type(error).__name__
    if len(first) > MAX_ERROR:
        first = first[: MAX_ERROR - 1] + "…"
    return first


@contextlib.contextmanager
def logged(item_type, name, arguments=None):
    """Log the call run in the block when it ends. ``item_type`` is "tool",
    "resource" or "prompt"."""
    if not logger.isEnabledFor(logging.INFO):
        yield
        return
    started = time.monotonic()
    outcome, error = "ok", None
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except PermissionDeniedError as e:
        outcome, error = "denied", e
        raise
    except BaseException as e:
        outcome, error = "error", e
        raise
    finally:
        what = name if item_type == "tool" else f"{item_type} {name}"
        if arguments:
            what = f"{what} {shorten(arguments)}"
        if len(what) > MAX_WHAT:
            what = what[: MAX_WHAT - 1] + "…"
        text = f"{what} -> {outcome} {time.monotonic() - started:.2f}s"
        if error is not None:
            text += f": {_describe_error(error)}"
        logger.info("mcp[%s] %s", _session.get(), text)
