import asyncio
import subprocess
import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from trame.app import get_server
from trame.modules import www
from wslink import register as export_rpc
from wslink.websocket import LinkProtocol


@pytest.mark.asyncio
async def test_child_server():
    server = get_server("test_child_server")
    server.start(exec_mode="task", port=0)
    child_server = server.create_child_server(prefix="child_")

    assert await server.ready
    assert await child_server.ready

    assert server.running
    assert child_server.running

    server.state.a = 1
    child_server.state.a = 2

    assert server.state.has("a")
    assert server.state.has("child_a")
    assert child_server.state.has("a")

    assert server.state.child_a == child_server.state.a

    server.state.flush()
    await server.network_completion

    assert server.get_server_state() == {
        "name": "test_child_server",
        "state": {
            "a": 1,
            "child_a": 2,
            "trame__busy": 1,
            "trame__client_only": [
                "trame__busy",
            ],
            "trame__favicon": None,
            "trame__module_scripts": [],
            "trame__mousetrap": [],
            "trame__scripts": [],
            "trame__styles": [],
            "trame__title": "Trame",
            "trame__vue_use": [],
            "trame__react_use": [],
        },
    }

    await asyncio.sleep(0.1)
    await server.stop()


def test_http_headers():
    server = get_server("test_http_headers")

    server.http_headers.shared_array_buffer = True
    server.http_headers.set_header("hello", "world")
    server.http_headers.set_header("hello2", "world2")
    server.http_headers.remove_header("hello2")

    assert server.http_headers.headers == {
        "hello": "world",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "require-corp",
        "Access-Control-Allow-Origin": "*",
    }
    server.http_headers.shared_array_buffer = False
    assert server.http_headers.headers == {
        "hello": "world",
    }
    assert server.http_headers.get_header("hello") == "world"


def test_enable_module():
    server = get_server("test_enable_module")
    child_server = server.create_child_server(prefix="child_")

    module = {
        "scripts": ["fake_url/script.js"],
        "state": {
            "a": 1,
            "b": 2,
        },
        "serve": {"data": "/tmp"},
    }

    assert child_server.enable_module(module)
    assert child_server.enable_module(www)

    # should skip since already loaded
    assert not server.enable_module(module)
    assert not server.enable_module(www)

    assert server.state.a == 1
    assert server.state.b == 2
    serve_conf = {
        k: v
        for k, v in server.serve.items()
        if not k.startswith("__trame_client_external_scripts")
    }
    assert serve_conf == {"data": "/tmp"}

    @server.change("a")
    def on_change(**_):
        pass

    @server.trigger("my_name")
    def another_method():
        pass

    assert server.state._change_callbacks["a"][0][0] == on_change
    assert server.trigger_name(another_method) == "my_name"
    assert server.name == "test_enable_module"

    # default is vue3
    assert server.client_type == "vue3"

    # can still be overridden
    server.client_type = "vue2"
    assert server.client_type == "vue2"

    # Can only be set once
    with pytest.raises(TypeError):
        server.client_type = "vue3"


def test_cli_args_collision(pytestconfig: pytest.Config):
    cli = pytestconfig.rootpath / "tests/data/test_cli.py"
    subprocess.run([sys.executable, str(cli), "--f", "foo"], check=True)


def test_cli():
    server = get_server("test_cli")
    child_server = server.create_child_server(prefix="child_")
    server.cli.add_argument("--data")
    child_server.cli.add_argument("--data2")
    args = server.cli.parse_known_args()[0]
    assert args.data is None
    assert args.data2 is None


@pytest.mark.asyncio
async def test_server_start_async():
    server = get_server("test_server_start_async")
    count = 0

    def on_start(s):
        nonlocal count
        count += 2
        assert server is s

    def on_ready(**_):
        nonlocal count
        count += 3

    child_server = server.create_child_server(prefix="child_")

    server.controller.on_server_start.add(on_start)
    server.controller.on_server_ready.add(on_ready)

    class TestProto(LinkProtocol):
        @export_rpc("pytest.protocol.test")
        def run(
            self,
        ):
            return 11

    def register_protocol(protocol):
        protocol.registerLinkProtocol(TestProto())

    child_server.add_protocol_to_configure(register_protocol)

    server.state.a = 10

    child_server.start(exec_mode="task", thread=True, port=0)

    assert await server.ready
    assert await child_server.ready

    # Should be a noop as already started
    server.start(exec_mode="task", port=0)

    assert server.protocol_call("pytest.protocol.test") == 11

    await asyncio.sleep(0.1)
    assert count == 5

    server.force_state_push("a")
    server.js_call("js_ref", "method", "arg1", "arg2")

    server.clear_state_client_cache("a")

    assert child_server.protocol == server.protocol
    assert child_server.port == server.port
    assert child_server.port != 0

    await child_server.stop()


def test_server_start_sync(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAME_ARGS", "--banner --no-http")
    monkeypatch.setenv("TRAME_LOG_NETWORK", str(tmp_path / "trame_net.log"))
    server = get_server("test_server_start_sync")
    server.serve.update(
        {
            "data": str(Path(__file__).parent.resolve()),
            "data2": (
                str(Path(__file__).parent.resolve()),
                "sync",
            ),  # don't remember usage...
        }
    )
    server.state.a = b"sdkfjhvlskdjhf"
    server.start(timeout=1, open_browser=False, port=0)


def test_ui():
    server = get_server("test_ui")
    server.ui.vnode  # noqa: B018


@pytest.mark.asyncio
async def test_server_ready_forwards_exceptions_in_ready_future():
    server_1 = get_server("test_ready_exception_forwarding_1")
    server_1.start(exec_mode="task", port=0)
    await server_1.ready

    server_2 = get_server("test_ready_exception_forwarding_2")
    server_2.start(exec_mode="task", port=server_1.port)
    with pytest.raises(OSError, match="error while attempting to bind on address"):
        await server_2.ready


@pytest.mark.asyncio
async def test_server_task_cancel_doesnt_hang_ready_future():
    server = get_server("test_cancel")
    task = server.start(exec_mode="task", port=0)
    task.cancel()
    await asyncio.wait_for(server.ready, timeout=1)


def _text_handler(text):
    async def handler(_request):
        return web.Response(text=text)

    return handler


@pytest.mark.asyncio
async def test_on_server_bind_routes_take_precedence():
    server = get_server("test_on_server_bind_routes")

    @server.controller.add("on_server_bind")
    def add_routes(wslink_server):
        wslink_server.app.router.add_routes(
            [
                web.get("/", _text_handler("custom root")),
                web.get("/index.html", _text_handler("custom index")),
                web.get("/api/hello", _text_handler("hello")),
            ]
        )

    server.start(exec_mode="task", port=0)
    assert await server.ready

    try:
        async with aiohttp.ClientSession() as session:
            for path, expected in [
                ("/", "custom root"),
                ("/index.html", "custom index"),
                ("/api/hello", "hello"),
            ]:
                url = f"http://localhost:{server.port}{path}"
                async with session.get(url, allow_redirects=False) as response:
                    assert response.status == 200, path
                    assert await response.text() == expected
    finally:
        await asyncio.sleep(0.1)
        await server.stop()
