"""Issue the authentication cookie on aiohttp, wslink's default web server.

The logic lives in :mod:`trame_server.auth`: this only copies the
``Set-Cookie`` headers it computes onto aiohttp responses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from aiohttp import web

from trame_server.auth import SECRET_PARAM, is_default, set_cookie_headers

logger = logging.getLogger("trame_server.auth")


def middleware(get_secret: Callable[[], str], get_port: Callable[[], int]):
    """aiohttp middleware adding :func:`~trame_server.auth.set_cookie_headers`
    to responses. ``get_secret`` returns the current secret and ``get_port``
    the port the server listens on."""

    @web.middleware
    async def trame_auth_cookie(request, handler):
        response = await handler(request)
        # Responses already sent (e.g. WebSocket) can no longer take headers
        if response.prepared:
            return response
        for value in set_cookie_headers(
            get_secret(),
            request.query.get(SECRET_PARAM),
            request.host,
            get_port(),
            request.headers.get("Cookie"),
            request.secure,
        ):
            response.headers.add("Set-Cookie", value)
        return response

    return trame_auth_cookie


def mount(
    wslink_server, get_secret: Callable[[], str], get_port: Callable[[], int]
) -> bool:
    """Add the cookie middleware to the web server wslink created, when it is
    aiohttp's and the secret is not the default, and return whether it did.
    Must run before the server starts."""
    if is_default(get_secret()):
        return False
    app = getattr(wslink_server, "app", None)
    if not isinstance(app, web.Application):
        logger.info(
            "The auth cookie is not issued: this web server is not aiohttp, "
            "so clients must send the secret, including after a reload"
        )
        return False
    app.middlewares.append(middleware(get_secret, get_port))
    return True
