import asyncio
import logging
import socket
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiohttp
import pytest
import pytest_asyncio
from trame.app import asynchronous, get_client, get_server

from trame_server.client import ConnectionStatus, WsLinkSession
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
        if client.connected == ConnectionStatus.CONNECTED:
            break
        await asyncio.sleep(0.1)

    # Only reported as connected once authenticated
    assert client.connected == ConnectionStatus.CONNECTED
    assert client._session.client_id is not None
    try:
        yield client
    finally:
        await asyncio.sleep(0.1)
        await client.disconnect()


def _logged(caplog, level, message):
    """Return the record matching level and message, if any"""
    for record in caplog.records:
        if record.levelname == level and record.getMessage() == message:
            return record
    return None


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
async def test_async_and_missing_trigger(server, client, caplog):
    @server.trigger("async_add")
    async def async_add(a, b):
        await asyncio.sleep(0.01)
        return a + b

    assert await client.call_trigger("async_add", [1, 2]) == 3

    assert await client.call_trigger("not_registered") is None
    assert _logged(caplog, "WARNING", "Trigger not_registered seems to be missing")


@pytest.mark.asyncio
async def test_lifecycle_and_js_error(server, client, caplog):
    on_custom = MagicMock()
    server.controller.on_custom = on_custom
    await _rpc(client, "trame.lifecycle.update", "custom")
    on_custom.assert_called_once_with()

    # Unknown life cycle name is a no-op
    await _rpc(client, "trame.lifecycle.update", "unknown_cycle")

    # JS error without handler is logged
    await _rpc(client, "trame.error.client", "boom")
    assert _logged(caplog, "ERROR", "JS Error => boom")

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
async def test_client_subscriptions(client, caplog):
    session = client._session
    received = []

    def broken(_):
        msg = "callback failure"
        raise ValueError(msg)

    session.register_subscription("custom.topic", received.append)
    session.register_subscription("custom.topic", broken)

    await session.on_msg_complete({"id": "publish:custom.topic:0", "result": {"x": 1}})
    assert received == [{"x": 1}]
    record = _logged(caplog, "ERROR", "Subscription callback error (custom.topic)")
    assert record.exc_info[0] is ValueError

    # Error without matching in-flight rpc
    await session.on_msg_complete({"id": "rpc:x:999", "error": "oops"})
    assert _logged(caplog, "ERROR", "Server error: oops")

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


@pytest.mark.asyncio
async def test_clear_state_client_cache(server, client):
    server.state.cached = 1
    server.state.flush()
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.cached == 1

    # Unknown keys are ignored
    server.clear_state_client_cache("never_sent", "cached")

    # Once cleared, an unchanged value is sent again
    client.state._pushed_state["cached"] = 0
    server.protocol.push_state_change({"cached": 1})
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.cached == 1


@pytest.mark.asyncio
async def test_late_response_after_timeout_keeps_client_alive(server, client):
    @server.trigger("slow")
    async def slow():
        await asyncio.sleep(0.3)
        return "late"

    @server.trigger("fast")
    def fast():
        return "fast"

    # Cancelling the call also cancels its pending future
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.call_trigger("slow"), timeout=0.05)

    # Let the late response arrive
    await asyncio.sleep(0.5)

    assert client._session.in_flight_rpc == {}
    assert await client.call_trigger("fast") == "fast"


@pytest.mark.asyncio
async def test_responses_without_pending_future(client):
    session = client._session
    client_id = session.client_id

    # System messages that nobody is waiting for
    await session.on_msg_complete({"id": "system:c0:99", "result": {"x": 1}})
    await session.on_msg_complete(
        {
            "id": WsLinkSession.AUTH_ID,
            "result": {"clientID": client_id, "maxMsgSize": 1024},
        }
    )
    assert session.client_id == client_id

    # Responses for futures that were cancelled
    for payload in [
        {"id": "rpc:x:1", "result": 1},
        {"id": "rpc:x:1", "error": "oops"},
        {"id": "system:c0:1", "result": 1},
    ]:
        future = session.loop.create_future()
        future.cancel()
        session.in_flight_rpc[payload["id"]] = future
        await session.on_msg_complete(payload)
        assert payload["id"] not in session.in_flight_rpc


@pytest.mark.asyncio
async def test_connected_status_follows_authentication(server):
    client = get_client(f"ws://localhost:{server.port}/ws")
    assert client.connected == ConnectionStatus.DISCONNECTED

    observed = []
    task = asynchronous.create_task(client.connect(secret="wslink-secret"))
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        status = client.connected
        client_id = client._session.client_id if client._session else None
        # Skip samples taken before the task started
        started = observed or status != ConnectionStatus.DISCONNECTED
        if started and (not observed or observed[-1][0] != status):
            observed.append((status, client_id))
        if status == ConnectionStatus.CONNECTED:
            break
        # Sample on every loop iteration to observe each transition
        await asyncio.sleep(0)

    statuses = [status for status, _ in observed]
    assert statuses == [ConnectionStatus.CONNECTING, ConnectionStatus.CONNECTED]
    # client_id is known as soon as we report being connected
    assert observed[-1][1] is not None

    await client.disconnect()
    await task
    assert client.connected == ConnectionStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_connect_authentication_failure(server):
    client = get_client(f"ws://localhost:{server.port}/ws")
    with pytest.raises(Exception, match="Authentication failed"):
        await asyncio.wait_for(client.connect(secret="wrong"), timeout=5)

    assert client.connected == ConnectionStatus.DISCONNECTED
    assert client._session is None


@pytest.mark.asyncio
async def test_connect_failure_allows_reconnect(server):
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        closed_port = sock.getsockname()[1]

    client = get_client(f"ws://localhost:{closed_port}/ws")
    with pytest.raises(aiohttp.ClientConnectionError):
        await client.connect()
    assert client.connected == ConnectionStatus.DISCONNECTED

    # Not stuck in CONNECTING, so a new attempt goes through
    task = asynchronous.create_task(
        client.connect(f"ws://localhost:{server.port}/ws", secret="wslink-secret")
    )
    for _ in range(50):
        if client.connected == ConnectionStatus.CONNECTED:
            break
        await asyncio.sleep(0.1)
    assert client.connected == ConnectionStatus.CONNECTED

    await client.disconnect()
    await task


@pytest.mark.asyncio
async def test_connection_closed_before_authentication():
    client = get_client("ws://unused")
    auth_response = asyncio.get_running_loop().create_future()

    async def auth(**_):
        return auth_response

    async def closed():
        pass

    client._session = SimpleNamespace(auth=auth)
    listen_task = asyncio.ensure_future(closed())

    with pytest.raises(ConnectionError, match="closed before authentication"):
        await client._wait_for_auth(listen_task, {})
    assert auth_response.cancelled()


@pytest.mark.asyncio
async def test_call_trigger_requires_connection():
    client = get_client("ws://unused")
    with pytest.raises(ConnectionError, match=r"not connected.*DISCONNECTED"):
        await client.call_trigger("anything")


@pytest.mark.asyncio
async def test_clear_state_client_cache_on_child_server(server, client):
    child_server = server.create_child_server(prefix="child_")
    child_server.state.value = 1
    child_server.state.flush()
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.child_value == 1
    assert "child_value" in server.protocol._clients_state

    # Names are given as seen by the child server, like force_state_push
    child_server.clear_state_client_cache("value")
    assert "child_value" not in server.protocol._clients_state

    # Once cleared, an unchanged value is sent again
    client.state._pushed_state["child_value"] = 0
    child_server.state.dirty("value")
    child_server.state.flush()
    await server.network_completion
    await asyncio.sleep(0.1)
    assert client.state.child_value == 1


class FakeWebSocket:
    def __init__(self, *msg_types):
        self._messages = [SimpleNamespace(type=t, data="text") for t in msg_types]

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for msg in self._messages:
            yield msg

    def exception(self):
        return RuntimeError("connection reset")


@pytest.mark.asyncio
async def test_listen_logs_websocket_events(caplog):
    caplog.set_level(logging.DEBUG, logger="trame_server.client")
    session = WsLinkSession(
        FakeWebSocket(
            aiohttp.WSMsgType.TEXT,
            aiohttp.WSMsgType.ERROR,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
        )
    )
    await session.listen()

    assert _logged(caplog, "CRITICAL", "wslink is not expecting text message:\n> text")
    assert _logged(caplog, "ERROR", "WebSocket error: connection reset")
    assert _logged(caplog, "DEBUG", "WebSocket CLOSING")
    assert _logged(caplog, "DEBUG", "WebSocket CLOSED")
