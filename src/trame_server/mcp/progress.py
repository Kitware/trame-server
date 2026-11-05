"""Progress notifications: what a tool or method reports through its
``Progress`` parameter, sent to the agent that asked for it.

A request carrying a ``progressToken`` in its ``_meta`` gets a
:class:`Reporter` for its duration, when its transport can send
notifications (``MCPProtocol.handle``'s ``notify``). The request's calls find
it in a context variable, which follows them into the tasks they create.
:func:`inject` passes it to a function that declares a ``Progress``
parameter, or passes a reporter that does nothing when the agent asked for no
progress.

MCP requires the value sent to grow, and nothing to be sent after the result.
So a report whose value doesn't grow is dropped, and its message goes with the
next one. Reports are also combined into at most one notification per
``MIN_INTERVAL``, the latest winning. The last one still waiting when the
call returns goes out just before the result.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging

from trame_common.obj.mcp import Progress

from trame_server.mcp.schema import progress_parameter

logger = logging.getLogger("trame_server.mcp")

__all__ = ["Reporter", "inject", "reporting"]

# Seconds between two notifications of one request, at least
MIN_INTERVAL = 0.1

# The decimal places by which a batch step's report without a total moves the
# value: about half a float's precision, leaving the other half for the steps
STEP_DIGITS = 8

_NO_PROGRESS = Progress()
_current = contextvars.ContextVar("trame_mcp_progress", default=None)


class Reporter(Progress):
    """Sends a request's progress with ``send(fields)``, an async callable
    taking the notification's ``progress``, ``total`` and ``message``."""

    def __init__(self, send, interval=MIN_INTERVAL):
        self._send = send
        self._interval = interval
        self._sent = None  # the last value sent
        self._pending = None  # (value, total) not sent yet
        self._message = None  # goes with the next notification
        self._next = 0.0  # loop time from which the next one may go
        self._flush = None  # the task sending what is pending, when due
        self._sending = asyncio.Lock()
        self._closed = False

    async def __call__(self, value, total=None, message=None):
        if self._closed:
            return
        if message is not None:
            self._message = message
        latest = self._pending[0] if self._pending else self._sent
        if latest is not None and not value > latest:
            return
        self._pending = (value, total)
        if self._flush is not None:
            return  # going out when due, as the latest
        delay = self._next - asyncio.get_running_loop().time()
        if delay <= 0:
            await self._send_pending()
        else:
            self._flush = asyncio.ensure_future(self._send_later(delay))

    async def _send_later(self, delay):
        await asyncio.sleep(delay)
        self._flush = None
        # Shielded: closing waits for a notification being written
        await asyncio.shield(self._send_pending())

    async def _send_pending(self):
        async with self._sending:
            if self._closed or self._pending is None:
                return
            value, total = self._pending
            fields = {"progress": value}
            if total is not None:
                fields["total"] = total
            if self._message is not None:
                fields["message"] = self._message
            self._pending, self._message, self._sent = None, None, value
            self._next = asyncio.get_running_loop().time() + self._interval
            try:
                await self._send(fields)
            except Exception:  # the client went away: the call goes on
                logger.debug("Sending progress failed", exc_info=True)
                self._closed = True

    async def close(self):
        """Called when the result is ready: send what is pending now, before the
        result, and nothing after it."""
        if self._flush is not None:
            self._flush.cancel()
            self._flush = None
        await self._send_pending()
        async with self._sending:
            self._closed = True


class _BatchStep(Progress):
    """The reporter a method gets during one step of an ``object_batch``. Its
    reports become progress within that step of the batch (step k of n).
    With a total, the value moves by the method's fraction of the step;
    without one, each report moves it by ``10**-STEP_DIGITS``, so that it
    still grows and goes out with its message."""

    def __init__(self, batch, index, count):
        self._batch = batch
        self._index = index
        self._count = count
        self._done = index  # the furthest within this step

    async def __call__(self, value, total=None, message=None):
        if total:
            done = self._index + min(max(value / total, 0.0), 1.0)
        else:
            tick = 10**-STEP_DIGITS
            done = min(round(self._done + tick, STEP_DIGITS), self._index + 1 - tick)
        self._done = max(self._done, done)
        await self._batch(done, total=self._count, message=message)


@contextlib.contextmanager
def reporting(reporter):
    """Make ``reporter`` the reporter of the calls made in the block (None when
    the agent asked for no progress)."""
    token = _current.set(reporter)
    try:
        yield
    finally:
        _current.reset(token)


def batch_step(index, count):
    """The reporter that the method of step ``index`` of ``count`` gets in a batch,
    or None when the agent asked for no progress."""
    batch = _current.get()
    return None if batch is None else _BatchStep(batch, index, count)


def current():
    """The reporter of the request being handled, or None."""
    return _current.get()


def inject(fn, arguments):
    """``arguments``, with the reporter added when ``fn`` declares a
    ``Progress`` parameter: the request's, or one that does nothing."""
    name = progress_parameter(fn)
    if name is None:
        return arguments
    return {**arguments, name: _current.get() or _NO_PROGRESS}
