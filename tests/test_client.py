import asyncio
import pytest

from trame.app import get_server, get_client, asynchronous


@pytest.mark.asyncio
async def test_client_connection():
    server = get_server("test_client_connection")
    server.start(exec_mode="task", port=0)
    assert await server.ready
    assert server.running

    url = f"ws://localhost:{server.port}/ws"
    client = get_client(url)
    asynchronous.create_task(client.connect(secret="wslink-secret"))
    await asyncio.sleep(0.1)

    # should be a noop
    await client.connect()
    assert client.connected == 2

    @client.change("a")
    def on_change(a, **_):
        assert a == 2

    @server.trigger("add")
    def server_method(*args):
        result = 0
        for v in args:
            result += v
        return result

    with server.state as state:
        state.a = 2

    await server.network_completion
    await asyncio.sleep(0.1)  # wait for client network

    assert server.state.a == client.state.a

    with client.state as state:
        state.b = {"a": 1, "b": 2, "_filter": ["b"]}

    await asyncio.sleep(0.1)  # wait for client network
    assert server.state.b == {"a": 1, "_filter": ["b"]}

    assert await client.call_trigger("add", [1, 2, 3]) == 6
    assert await client.call_trigger("add") == 0

    await asyncio.sleep(0.1)
    await client.diconnect()
    await asyncio.sleep(0.5)
    await server.stop()
