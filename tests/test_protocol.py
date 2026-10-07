import asyncio
import io
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from trame.app import asynchronous, get_client, get_server

from trame_server.protocol import CoreServer


@pytest_asyncio.fixture
async def server():
    server = get_server("test_protocol")
    server.start(exec_mode="task", port=0)
    assert await server.ready
    try:
        yield server
    finally:
        await asyncio.sleep(0.2)
        await server.stop()


@pytest_asyncio.fixture
async def client(server):
    client = get_client(f"ws://localhost:{server.port}/ws")
    asynchronous.create_task(client.connect(secret="wslink-secret"))

    for _ in range(20):
        if client._session and client._session.client_id is not None:
            break
        await asyncio.sleep(0.1)

    assert client.connected == 2
    try:
        yield client
    finally:
        await asyncio.sleep(0.1)
        await client.disconnect()


async def _rpc(client, method, *args):
    return await (await client._session.call(method, list(args)))


@pytest.mark.asyncio
async def test_rpc_error_keeps_client_alive(server, client):
    with pytest.raises(Exception, match="Unregistered method called"):
        await _rpc(client, "trame.does.not.exist")

    # The connection must still be usable after an error
    @server.trigger("ping")
    def ping():
        return "pong"

    assert await client.call_trigger("ping") == "pong"


@pytest.mark.asyncio
async def test_unserializable_args_raise_serialization_error(server, client):
    @server.trigger("echo")
    def echo(value):
        return value

    pending = dict(client._session.in_flight_rpc)

    with pytest.raises(TypeError, match="can not serialize"):
        await client.call_trigger("echo", [object()])

    with pytest.raises(TypeError, match="can not serialize"):
        await client._session.auth(secret=object())

    # Failed requests are not left waiting for a response
    assert client._session.in_flight_rpc == pending

    # Connection is still usable
    assert await client.call_trigger("echo", [1]) == 1


@pytest.mark.asyncio
async def test_async_and_missing_trigger(server, client):
    @server.trigger("async_add")
    async def async_add(a, b):
        await asyncio.sleep(0.01)
        return a + b

    assert await client.call_trigger("async_add", [1, 2]) == 3

    with io.StringIO() as buf, redirect_stdout(buf):
        assert await client.call_trigger("not_registered") is None
        assert "Trigger not_registered seems to be missing" in buf.getvalue()


@pytest.mark.asyncio
async def test_lifecycle_and_js_error(server, client):
    on_custom = MagicMock()
    server.controller.on_custom = on_custom
    await _rpc(client, "trame.lifecycle.update", "custom")
    on_custom.assert_called_once_with()

    # Unknown life cycle name is a no-op
    await _rpc(client, "trame.lifecycle.update", "unknown_cycle")

    # JS error without handler is printed
    with io.StringIO() as buf, redirect_stdout(buf):
        await _rpc(client, "trame.error.client", "boom")
        assert "JS Error => boom" in buf.getvalue()

    # JS error with handler
    on_error = MagicMock()
    server.controller.on_error = on_error
    await _rpc(client, "trame.error.client", "boom again")
    on_error.assert_called_once_with("boom again")


@pytest.mark.asyncio
async def test_get_state_and_force_push(server, client):
    server.state.forced = 1
    server.state.flush()
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.forced == 1

    full_state = await _rpc(client, "trame.state.get")
    assert full_state["state"]["forced"] == 1

    # Client corrupts its local copy, server forces a resend
    client.state._pushed_state["forced"] = 0
    server.force_state_push("forced")
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.forced == 1

    # No keys is a no-op
    server.force_state_push()


@pytest.mark.asyncio
async def test_protocol_call(server):
    assert server.protocol_call("trame.does.not.exist") is None
    assert server.protocol_call("trame.state.get")["state"] is not None


@pytest.mark.asyncio
async def test_client_subscriptions(client):
    session = client._session
    received = []

    def broken(_):
        msg = "callback failure"
        raise ValueError(msg)

    session.register_subscription("custom.topic", received.append)
    session.register_subscription("custom.topic", broken)

    with io.StringIO() as buf, redirect_stdout(buf):
        await session.on_msg_complete(
            {"id": "publish:custom.topic:0", "result": {"x": 1}}
        )
        assert "Subscription callback error" in buf.getvalue()
    assert received == [{"x": 1}]

    # Error without matching in-flight rpc
    with io.StringIO() as buf, redirect_stdout(buf):
        await session.on_msg_complete({"id": "rpc:x:999", "error": "oops"})
        assert "Server error: oops" in buf.getvalue()

    # Notification without id is ignored
    await session.on_msg_complete({"result": None})

    session.unregister_subscription("custom.topic", broken)
    assert session.subscriptions["custom.topic"] == [received.append]
    session.unregister_subscription("custom.topic", received.append)
    assert "custom.topic" not in session.subscriptions
    # Unknown topic/callback is a no-op
    session.unregister_subscription("custom.topic", received.append)


def test_configure_auth_key(tmp_path):
    previous = CoreServer.authentication_token
    try:
        CoreServer.configure(Namespace(authKeyFile=None, authKey="from-arg"))
        assert CoreServer.authentication_token == "from-arg"

        key_file = tmp_path / "key.txt"
        key_file.write_text("from-file\n")
        CoreServer.configure(Namespace(authKeyFile=str(key_file), authKey="unused"))
        assert CoreServer.authentication_token == "from-file"
    finally:
        CoreServer.authentication_token = previous
