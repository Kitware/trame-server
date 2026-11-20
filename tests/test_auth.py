import asyncio
import logging
import time
from http.cookies import SimpleCookie
from types import SimpleNamespace

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from trame.app import get_server

from trame_server import auth
from trame_server.auth import DEFAULT_SECRET, MAX_COOKIES, resolve_secret, stale_cookies
from trame_server.auth import aiohttp as auth_aiohttp
from trame_server.client import WsLinkSession

# -----------------------------------------------------------------------------
# Secret and cookie
# -----------------------------------------------------------------------------


def test_resolve_secret(tmp_path):
    assert resolve_secret() == DEFAULT_SECRET
    assert resolve_secret("mine") == "mine"

    secret = resolve_secret("auto")
    assert len(secret) >= 40
    assert resolve_secret("auto") != secret

    key_file = tmp_path / "key"
    key_file.write_text(" from-file \n")
    assert resolve_secret("auto", str(key_file)) == "from-file"


def test_check_secret():
    assert auth.check_secret("s3cret", "s3cret")
    assert not auth.check_secret("s3cret", "s3cret ")
    assert not auth.check_secret("s3cret", "")
    assert not auth.check_secret("s3cret", None)
    assert not auth.check_secret("s3cret", 123)
    assert not auth.check_secret("s3cret", ["s3cret"])
    assert not auth.check_secret(None, "s3cret")
    # Non-ASCII values compare without raising
    assert not auth.check_secret("s3cret", "sécret")


def test_default_secret_issues_no_cookie():
    for secret in (DEFAULT_SECRET, "", None):
        assert auth.is_default(secret)
        assert auth.url_query_params(secret) == {}
        assert auth.cookie_for(secret, secret, "localhost:8080", 8080) is None
    cookie = f"{auth.cookie_name('localhost:8080', 8080)}={auth.cookie_value(DEFAULT_SECRET)}"
    headers = {"Host": "localhost:8080", "Cookie": cookie}
    assert not auth.check_cookie(DEFAULT_SECRET, headers, 8080)


def test_cookie():
    mac = auth.cookie_mac("s3cret")
    assert auth.url_query_params("s3cret") == {"secret": "s3cret"}
    # The cookie holds an HMAC, not the secret: a leaked cookie cannot pass as it
    assert "s3cret" not in auth.cookie_value("s3cret")
    assert not auth.check_secret("s3cret", mac)
    assert auth.cookie_mac("other") != mac
    assert auth.cookie_value("s3cret", 123) == f"123.{mac}"

    assert auth.cookie_for("s3cret", "wrong", "localhost:8080", 8080) is None
    name, value = auth.cookie_for("s3cret", "s3cret", "localhost:8080", 8080)
    assert name == "trame-auth-localhost-8080-8080"
    timestamp, value_mac = value.split(".")
    assert abs(int(timestamp) - time.time()) < 5
    assert value_mac == mac
    assert (
        auth.cookie_name("hub.example.com", 8080) == "trame-auth-hub-example-com-8080"
    )
    # Same host name, different servers => different cookies
    assert auth.cookie_name("localhost:8080", 9000) != name
    assert auth.cookie_name("localhost:9001", 8080) != auth.cookie_name(
        "localhost:9002", 8080
    )


def _headers(origin=None, host="localhost:8080", value=None):
    value = value or auth.cookie_value("s3cret")
    headers = {
        "Host": host,
        "Cookie": f"other=1; {auth.cookie_name(host, 8080)}={value}",
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (None, True),  # not a browser page
        ("http://localhost:8080", True),
        ("HTTP://LOCALHOST:8080/", True),
        ("http://localhost:3000", False),  # same site, other port
        ("http://127.0.0.1:8080", False),
        ("https://evil.example.com", False),
        ("null", False),  # sandboxed frame or file://
    ],
)
def test_check_cookie_origin(origin, allowed):
    assert auth.check_cookie("s3cret", _headers(origin), 8080) is allowed


def test_check_cookie_invalid():
    mac = auth.cookie_mac("s3cret")
    assert not auth.check_cookie("s3cret", _headers(value="forged"), 8080)
    assert not auth.check_cookie("s3cret", _headers(value=f"123.{'0' * 64}"), 8080)
    # The HMAC alone, without a timestamp
    assert not auth.check_cookie("s3cret", _headers(value=mac), 8080)
    # The timestamp only orders cookies: any one goes
    assert auth.check_cookie("s3cret", _headers(value=f"0.{mac}"), 8080)
    # A cookie for another secret, e.g. before updateSecret()
    assert not auth.check_cookie("changed", _headers(), 8080)
    assert not auth.check_cookie("s3cret", {"Host": "localhost:8080"}, 8080)
    assert not auth.check_cookie(
        "s3cret", {"Host": "localhost:8080", "Cookie": "not a cookie;;="}, 8080
    )
    # Cookie for another server sharing the host name
    assert not auth.check_cookie("s3cret", _headers(), 9000)
    headers = _headers()
    del headers["Host"]
    assert not auth.check_cookie("s3cret", headers, 8080)


def test_stale_cookies():
    cookies = {f"trame-auth-localhost-{i}-{i}": f"{i + 1}.mac" for i in range(30)}
    cookies["other"] = "1"
    cookies["trame-auth-bad"] = "not-a-timestamp"
    new = "trame-auth-localhost-29-29"
    stale = stale_cookies(cookies, new)
    # The new cookie and the 19 newest others stay, the rest goes
    assert len(cookies) - 1 - len(stale) == MAX_COOKIES
    assert set(stale) == {
        "trame-auth-bad",
        *(f"trame-auth-localhost-{i}-{i}" for i in range(10)),
    }
    assert stale_cookies({"other": "1", new: "1.mac"}, new) == []
    assert stale_cookies(cookies, "trame-auth-new", limit=31) == ["trame-auth-bad"]


def test_parse_cookie_header():
    assert auth.parse_cookie_header(None) == {}
    assert auth.parse_cookie_header("a=1; b=x=y;c; =d; a=2") == {"a": "1", "b": "x=y"}


def _morsel(set_cookie_header):
    (morsel,) = SimpleCookie(set_cookie_header).values()
    return morsel


def test_set_cookie_headers():
    host_port = ("localhost:8080", 8080)
    assert auth.set_cookie_headers("s3cret", None, *host_port) == []
    assert auth.set_cookie_headers("s3cret", "wrong", *host_port) == []
    assert auth.set_cookie_headers(DEFAULT_SECRET, DEFAULT_SECRET, *host_port) == []

    (header,) = auth.set_cookie_headers("s3cret", "s3cret", *host_port)
    morsel = _morsel(header)
    assert morsel.key == "trame-auth-localhost-8080-8080"
    assert morsel["path"] == "/"
    assert morsel["httponly"]
    assert morsel["samesite"] == "Strict"
    assert not morsel["secure"]
    cookie = {"Host": "localhost:8080", "Cookie": f"{morsel.key}={morsel.value}"}
    assert auth.check_cookie("s3cret", cookie, 8080)

    (header,) = auth.set_cookie_headers("s3cret", "s3cret", *host_port, secure=True)
    assert _morsel(header)["secure"]

    # Cookies of 25 other trame servers, the oldest first, and one trame
    # cannot have set, which stays
    others = [f"trame-auth-localhost-{4000 + i}-{4000 + i}" for i in range(25)]
    cookie_header = "; ".join(
        [
            "other=1",
            "trame-auth-x(y)=0.mac",
            *(f"{name}={i}.mac" for i, name in enumerate(others)),
        ]
    )
    *deleted, own = auth.set_cookie_headers(
        "s3cret", "s3cret", *host_port, cookie_header
    )
    deleted = [_morsel(header) for header in deleted]
    assert {m.key for m in deleted} == set(others[:6])
    assert all(m["max-age"] == "0" and m["path"] == "/" for m in deleted)
    assert _morsel(own).key == "trame-auth-localhost-8080-8080"


def test_mount(caplog):
    caplog.set_level(logging.INFO, logger="trame_server.auth")
    other = SimpleNamespace(app=None)  # generic, jupyter or tornado backend

    # Default secret: no cookie, nothing to say
    assert not auth_aiohttp.mount(other, lambda: DEFAULT_SECRET, lambda: 8080)
    assert caplog.records == []

    assert not auth_aiohttp.mount(other, lambda: "s3cret", lambda: 8080)
    assert "not aiohttp" in caplog.text

    app = web.Application()
    assert auth_aiohttp.mount(SimpleNamespace(app=app), lambda: "s3cret", lambda: 8080)
    assert len(app.middlewares) == 1


# -----------------------------------------------------------------------------
# Server
# -----------------------------------------------------------------------------


async def _start(name, monkeypatch, trame_args=None, configure=None):
    if trame_args is None:
        monkeypatch.delenv("TRAME_ARGS", raising=False)
    else:
        monkeypatch.setenv("TRAME_ARGS", trame_args)
    server = get_server(name)
    if configure is not None:
        server.add_protocol_to_configure(configure)
    server.start(exec_mode="task", port=0)
    assert await server.ready
    return server


@pytest_asyncio.fixture
async def auto_server(monkeypatch):
    server = await _start("test_auth_auto", monkeypatch, "--authKey auto")
    try:
        yield server
    finally:
        await asyncio.sleep(0.1)
        await server.stop()


async def _page_cookies(server, query, cookie=None):
    """Set-Cookie headers of the response to a page request."""
    headers = {"Cookie": cookie} if cookie else {}
    url = f"http://localhost:{server.port}/index.html?{query}"
    async with (
        aiohttp.ClientSession() as http,
        http.get(url, headers=headers) as response,
    ):
        assert response.status == 200
        return response.headers.getall("Set-Cookie", [])


async def _authenticates(server, secret, origin=None, cookie=None):
    """Whether a WebSocket opened with the given Origin and Cookie headers
    authenticates with ``secret``."""
    headers = {}
    if origin:
        headers["Origin"] = origin
    if cookie:
        headers["Cookie"] = cookie
    async with (
        aiohttp.ClientSession() as http,
        http.ws_connect(f"ws://localhost:{server.port}/ws", headers=headers) as ws,
    ):
        session = WsLinkSession(ws)
        listen_task = asyncio.create_task(session.listen())
        try:
            await asyncio.wait_for(await session.auth(secret=secret), 5)
            return True
        except Exception:
            return False
        finally:
            await ws.close()
            await listen_task


@pytest.mark.asyncio
async def test_auto_secret(auto_server):
    secret = auto_server.url_query_params["secret"]
    assert auto_server.server_options.authKey == secret
    assert await _authenticates(auto_server, secret)
    assert await _authenticates(auto_server, secret, origin="https://evil.example.com")
    assert not await _authenticates(auto_server, DEFAULT_SECRET)


@pytest.mark.asyncio
async def test_auto_cookie(auto_server):
    port = auto_server.port
    secret = auto_server.url_query_params["secret"]

    assert await _page_cookies(auto_server, "secret=wrong") == []
    (set_cookie,) = await _page_cookies(auto_server, f"secret={secret}&ui=main")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Path=/" in set_cookie
    assert secret not in set_cookie
    (morsel,) = SimpleCookie(set_cookie).values()
    assert morsel.key == f"trame-auth-localhost-{port}-{port}"
    cookie = f"{morsel.key}={morsel.value}"

    # The client no longer has the secret (reload, new tab) and sends the default
    own = f"http://localhost:{port}"
    assert await _authenticates(auto_server, DEFAULT_SECRET, origin=own, cookie=cookie)
    assert await _authenticates(auto_server, DEFAULT_SECRET, cookie=cookie)
    assert await _authenticates(auto_server, None, origin=own, cookie=cookie)
    # Pages from elsewhere, even on this machine, cannot use the cookie
    for origin in ("http://localhost:3000", "https://evil.example.com", "null"):
        assert not await _authenticates(
            auto_server, DEFAULT_SECRET, origin=origin, cookie=cookie
        )
    assert not await _authenticates(
        auto_server, DEFAULT_SECRET, origin=own, cookie=f"{morsel.key}=forged"
    )


@pytest.mark.asyncio
async def test_auto_cookie_cap(auto_server):
    secret = auto_server.url_query_params["secret"]
    # Cookies of 25 other trame servers, the oldest first
    others = [f"trame-auth-localhost-{4000 + i}-{4000 + i}" for i in range(25)]
    cookie = "; ".join(
        ["other=1", *(f"{name}={i}.mac" for i, name in enumerate(others))]
    )
    set_cookies = await _page_cookies(auto_server, f"secret={secret}", cookie)
    morsels = {m.key: m for c in set_cookies for m in SimpleCookie(c).values()}
    deleted = {name for name, m in morsels.items() if m["max-age"] == "0"}
    # Room for 19 others next to this server's cookie: the 6 oldest go
    assert deleted == set(others[:6])
    assert f"trame-auth-localhost-{auto_server.port}-{auto_server.port}" in morsels
    assert len(morsels) == 7


async def _cookie(server, secret):
    """The ``name=value`` of the cookie set on a page request with ``secret``."""
    (set_cookie,) = await _page_cookies(server, f"secret={secret}")
    (morsel,) = SimpleCookie(set_cookie).values()
    return f"{morsel.key}={morsel.value}"


@pytest.mark.asyncio
async def test_update_secret(auto_server):
    old = auto_server.url_query_params["secret"]
    old_cookie = await _cookie(auto_server, old)
    own = f"http://localhost:{auto_server.port}"

    # The protocol's secret is the only one checked
    auto_server.protocol.updateSecret("changed")
    assert auto_server.url_query_params == {"secret": "changed"}
    assert await _authenticates(auto_server, "changed")
    assert not await _authenticates(auto_server, old)
    # Cookies of the old secret no longer authenticate, nor does it set new ones
    assert not await _authenticates(
        auto_server, DEFAULT_SECRET, origin=own, cookie=old_cookie
    )
    assert await _page_cookies(auto_server, f"secret={old}") == []
    new_cookie = await _cookie(auto_server, "changed")
    assert await _authenticates(
        auto_server, DEFAULT_SECRET, origin=own, cookie=new_cookie
    )


@pytest.mark.asyncio
async def test_default_secret(monkeypatch):
    server = await _start("test_auth_default", monkeypatch)
    try:
        assert server.url_query_params == {}
        assert server.server_options.authKey == DEFAULT_SECRET
        assert await _page_cookies(server, f"secret={DEFAULT_SECRET}") == []
        assert await _authenticates(server, DEFAULT_SECRET)
        assert await _authenticates(server, DEFAULT_SECRET, origin="https://evil.com")
        assert not await _authenticates(server, "wrong")

        # As with wslink's own check, updateSecret() changes the accepted secret
        server.protocol.updateSecret("changed")
        assert await _authenticates(server, "changed")
        assert not await _authenticates(server, DEFAULT_SECRET)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_custom_validate_token(monkeypatch):
    # The pattern the docs give to extend trame's check
    def accept_issued_tokens(protocol):
        trame_check = protocol.validateToken

        async def validate_token(token, client_id):
            return await trame_check(token, client_id) or token == "issued"

        protocol.validateToken = validate_token

    server = await _start(
        "test_auth_custom", monkeypatch, "--authKey auto", accept_issued_tokens
    )
    try:
        secret = server.url_query_params["secret"]
        own = f"http://localhost:{server.port}"
        assert await _authenticates(server, "issued")
        # trame's own check still applies: the secret, or the cookie
        assert await _authenticates(server, secret)
        cookie = await _cookie(server, secret)
        assert await _authenticates(server, DEFAULT_SECRET, origin=own, cookie=cookie)
        assert not await _authenticates(server, "wrong")
        assert not await _authenticates(server, DEFAULT_SECRET)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_secret_per_server(monkeypatch):
    first = await _start("test_auth_first", monkeypatch, "--authKey auto")
    second = await _start("test_auth_second", monkeypatch, "--authKey auto")
    try:
        first_secret = first.url_query_params["secret"]
        second_secret = second.url_query_params["secret"]
        assert first_secret != second_secret
        assert await _authenticates(first, first_secret)
        assert await _authenticates(second, second_secret)
        assert not await _authenticates(first, second_secret)
    finally:
        await first.stop()
        await second.stop()


def test_child_server_url_query_params():
    server = get_server("test_auth_child")
    child = server.create_child_server()
    assert child.url_query_params == {}
    server._root_protocol = SimpleNamespace(secret="s3cret")
    assert child.url_query_params == {"secret": "s3cret"}
