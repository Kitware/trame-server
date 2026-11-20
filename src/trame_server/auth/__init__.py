"""WebSocket authentication.

A WebSocket connection is authenticated in one of two ways, as in
jupyter_server:

1. **The secret**, sent by the client in wslink's ``hello`` message. Knowing
   the secret is proof enough, so the origin of the page is not checked.
   Proxies, iframes and Python clients rely on this.
2. **A cookie**, set by the server on a page request that carries the right
   ``?secret=...``. The browser sends it back on later requests, so a
   reload or a new tab still connects once the client has removed the secret
   from its URL. Browsers attach cookies whichever page opens the
   connection, so the cookie only counts when the ``Origin`` of the WebSocket
   request is the server itself.

   Its name holds the address the browser used and the port the server listens
   on, so each server has its own cookie and replaces it when setting it again.
   Its value is the time it was set and an HMAC of the secret. Browsers send
   every cookie of a host with each request to it, whatever the port, so a
   server setting its cookie also deletes the oldest trame cookies beyond
   :data:`MAX_COOKIES`.

The secret comes from ``--authKeyFile``, then ``--authKey``: ``auto``
generates a random one, any other value is used as is. Without either, the
secret is wslink's well-known default, kept for backward compatibility. With
the default, no cookie is issued and URLs do not carry the secret.

The functions take the secret as an argument instead of keeping a copy: the
caller holds it (wslink's protocol, in its ``secret`` attribute), so changing
it there changes what every check accepts, cookies included.

This package does not depend on wslink, trame's ``Server`` or any web
framework, so it can move to wslink. Requests and responses are plain
headers: :func:`check_cookie` reads those of the WebSocket opening, and
:func:`set_cookie_headers` gives the ``Set-Cookie`` headers of a page
response. Each web server needs a small adapter to issue the cookie:
:mod:`trame_server.auth.aiohttp` for wslink's default backend. With other
backends, only the secret authenticates.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Mapping
from http.cookies import Morsel
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_SECRET = "wslink-secret"
"""wslink's default ``--authKey``, known to every client."""

AUTO_SECRET = "auto"
"""``--authKey`` value asking for a random secret on every start."""

SECRET_PARAM = "secret"
"""URL query parameter carrying the secret to the browser client."""

COOKIE_PREFIX = "trame-auth-"
"""Start of the name of every trame authentication cookie."""

MAX_COOKIES = 20
"""Number of trame cookies a browser keeps per host: setting one deletes the
oldest beyond it. Every cookie of a host goes with each request to it, and web
servers refuse requests whose headers grow too large (8 KB for aiohttp)."""

_NON_ALPHANUM = re.compile(r"[^A-Za-z0-9]+")
_COOKIE_NAME = re.compile(rf"{COOKIE_PREFIX}[A-Za-z0-9-]+")
# Message of the cookie's HMAC, keyed with the secret. Fixed, so the cookie
# stays valid as long as the secret does, across restarts too
_COOKIE_MAC_LABEL = b"trame-auth-cookie"


# -----------------------------------------------------------------------------
# Secret
# -----------------------------------------------------------------------------


def resolve_secret(auth_key=None, auth_key_file=None) -> str:
    """Return the secret for the given ``--authKey`` and ``--authKeyFile``
    values. The file takes precedence."""
    if auth_key_file:
        return Path(auth_key_file).read_text().strip()
    if auth_key == AUTO_SECRET:
        return secrets.token_urlsafe(32)
    if auth_key:
        return auth_key
    return DEFAULT_SECRET


def is_default(secret) -> bool:
    """Whether ``secret`` is wslink's well-known default, or empty: anyone can
    send it, so it gets no cookie and URLs do not need it."""
    return not secret or secret == DEFAULT_SECRET


def url_query_params(secret) -> dict[str, str]:
    """URL query parameters a browser client needs to authenticate: empty
    with the default secret, which clients already use."""
    return {} if is_default(secret) else {SECRET_PARAM: secret}


def check_secret(secret, value) -> bool:
    """Whether ``value`` is ``secret``."""
    return (
        isinstance(secret, str)
        and isinstance(value, str)
        and hmac.compare_digest(value.encode(), secret.encode())
    )


# -----------------------------------------------------------------------------
# Cookie
# -----------------------------------------------------------------------------


def cookie_name(host: str, port: int) -> str:
    """Cookie name for a server reached as ``host`` (the ``Host`` header) and
    listening on ``port``. Cookies ignore ports, so both are part of the name
    to keep apart servers sharing a host name, whether directly, behind a
    proxy or through port mapping."""
    return _NON_ALPHANUM.sub("-", f"{COOKIE_PREFIX}{host}-{port}")


def cookie_mac(secret: str) -> str:
    """HMAC of ``secret``, held by the cookie. Derived rather than the secret
    itself: a leaked cookie must not pass as the secret, which skips the
    origin check."""
    return hmac.new(secret.encode(), _COOKIE_MAC_LABEL, hashlib.sha256).hexdigest()


def cookie_value(secret: str, timestamp: int | None = None) -> str:
    """Cookie value: ``<timestamp>.<HMAC of the secret>``. The timestamp, now
    by default, only tells which cookies are the oldest."""
    if timestamp is None:
        timestamp = int(time.time())
    return f"{timestamp}.{cookie_mac(secret)}"


def cookie_for(secret, query_secret, host: str, port: int) -> tuple[str, str] | None:
    """The ``(name, value)`` of the cookie to set on the response to a request
    whose ``?secret=`` is ``query_secret``, or None."""
    if is_default(secret) or not host or not check_secret(secret, query_secret):
        return None
    return cookie_name(host, port), cookie_value(secret)


def parse_cookie_header(header: str | None) -> dict[str, str]:
    """Map the names of the cookies in a ``Cookie`` request header to their
    values. Parts that are not ``name=value`` are skipped, and the first of
    cookies sharing a name wins."""
    cookies = {}
    for part in (header or "").split(";"):
        name, eq, value = part.strip().partition("=")
        if eq and name:
            cookies.setdefault(name.strip(), value.strip())
    return cookies


def origin_allowed(origin: str | None, host: str) -> bool:
    """Whether a page from ``origin`` may use the cookie on a server reached as
    ``host``: only the server's own pages. Requests without ``Origin`` do not
    come from a browser page and are allowed."""
    if origin is None:
        return True
    try:
        netloc = urlsplit(origin.strip().rstrip("/").lower()).netloc
    except ValueError:
        return False
    # "null" (sandboxed frames, file://) has no netloc
    return bool(netloc) and netloc == host.lower()


def check_cookie(secret, headers: Mapping[str, str], port: int) -> bool:
    """Whether a WebSocket opening request with ``headers`` is authenticated by
    its cookie: the cookie is valid for ``secret`` and its ``Origin`` is
    allowed."""
    if is_default(secret) or not isinstance(secret, str):
        return False
    host = headers.get("Host")
    if not host or not origin_allowed(headers.get("Origin"), host):
        return False
    value = parse_cookie_header(headers.get("Cookie")).get(cookie_name(host, port))
    if value is None:
        return False
    _, dot, mac = value.partition(".")
    return bool(dot) and hmac.compare_digest(mac.encode(), cookie_mac(secret).encode())


def _cookie_timestamp(value: str) -> int:
    try:
        return int(value.partition(".")[0])
    except ValueError:
        return 0


def stale_cookies(
    cookies: Mapping[str, str], name: str, limit: int = MAX_COOKIES
) -> list[str]:
    """Names of the trame cookies to delete when setting the cookie ``name``, so
    that at most ``limit`` remain: the oldest ones. ``cookies`` maps the names
    of the cookies a request carried to their values."""
    others = sorted(
        (o for o in cookies if _COOKIE_NAME.fullmatch(o) and o != name),
        key=lambda o: _cookie_timestamp(cookies[o]),
        reverse=True,
    )
    return others[max(limit - 1, 0) :]


def _set_cookie_header(name: str, value: str, secure: bool, delete=False) -> str:
    morsel = Morsel()
    morsel.set(name, value, value)
    morsel["path"] = "/"
    morsel["httponly"] = True
    morsel["samesite"] = "Strict"
    morsel["secure"] = secure
    if delete:
        morsel["max-age"] = 0
    return morsel.OutputString()


def set_cookie_headers(
    secret,
    query_secret,
    host: str,
    port: int,
    cookie_header: str | None = None,
    secure: bool = False,
) -> list[str]:
    """``Set-Cookie`` header values for the response to a page request: when
    its ``?secret=`` is ``query_secret`` and is right, the deletion of the
    oldest trame cookies beyond :data:`MAX_COOKIES`, then this server's cookie.
    Empty otherwise.

    ``host`` is the request's ``Host`` header, ``port`` the port the server
    listens on, ``cookie_header`` the request's ``Cookie`` header and
    ``secure`` whether the request came over HTTPS."""
    cookie = cookie_for(secret, query_secret, host, port)
    if cookie is None:
        return []
    name, value = cookie
    stale = stale_cookies(parse_cookie_header(cookie_header), name)
    return [
        *(_set_cookie_header(o, "", secure, delete=True) for o in stale),
        _set_cookie_header(name, value, secure),
    ]
