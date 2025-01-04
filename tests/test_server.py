import asyncio
import pytest

from trame.app import get_server
from trame.modules import www


@pytest.mark.asyncio
async def test_child_server():
    server = get_server()
    server.start(exec_mode="task")
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
        "name": "trame",
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
        },
    }

    await asyncio.sleep(0.1)
    await server.stop()


def test_http_headers():
    server = get_server()

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
    server = get_server()
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
    assert server.serve == {"data": "/tmp"}

    @server.change("a")
    def on_change(**_):
        pass

    @server.trigger("my_name")
    def another_method():
        pass

    assert server.state._change_callbacks["a"][0] == on_change
    assert server.trigger_name(another_method) == "my_name"
    assert server.name == "trame"

    # default is vue3
    assert server.client_type == "vue3"

    # can still be overridden
    server.client_type = "vue2"
    assert server.client_type == "vue2"

    # Can only be set once
    with pytest.raises(TypeError):
        server.client_type = "vue3"


def test_cli():
    server = get_server()
    child_server = server.create_child_server(prefix="child_")
    server.cli.add_argument("--data")
    child_server.cli.add_argument("--data2")
    args = server.cli.parse_known_args()[0]
    assert args.data is None
    assert args.data2 is None
