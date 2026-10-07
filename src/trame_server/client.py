import asyncio
import logging
import os
import traceback
from enum import IntEnum

import aiohttp
import msgpack
from wslink.chunking import UnChunker, generate_chunks

from trame_server.utils import asynchronous

from .state import State

MAX_MSG_SIZE = int(os.environ.get("WSLINK_MAX_MSG_SIZE") or 4194304)

logger = logging.getLogger(__name__)


class ConnectionStatus(IntEnum):
    """Connection status of a Client"""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class WsLinkSession:
    CLIENT_ERROR = -32099
    AUTH_ID = "system:c0:0"

    def __init__(self, ws):
        self.loop = asyncio.get_running_loop()
        self.attachment_atomic = asyncio.Lock()
        self.ws = ws
        self.msg_count = 0
        self.bin_id = 1
        self.subscriptions = {}
        self.client_id = None
        self.unchunker = UnChunker()
        self.in_flight_rpc = {}

    async def on_msg_complete(self, payload):
        # Notification-only message from the server - should be binary attachment header
        if "id" not in payload:
            return

        msg_id = payload.get("id")
        msg_type, msg_topic, _ = msg_id.split(":")
        # Remove right away so we never leave a stale entry behind
        future = self.in_flight_rpc.pop(msg_id, None)

        # Skip futures that were already resolved or cancelled (e.g. timeout)
        pending = future is not None and not future.done()

        # Error
        if "error" in payload:
            if pending:
                future.set_exception(Exception(payload.get("error", "Server error")))
            elif future is None:
                print("Server error:", payload.get("error"))

            return

        # Normal processing
        msg_result = payload.get("result")

        # RPC
        if msg_type == "rpc" and pending:
            future.set_result(msg_result)

        # Publish
        if msg_type == "publish" and msg_topic in self.subscriptions:
            event = msg_result
            for fn in self.subscriptions[msg_topic]:
                try:
                    fn(event)
                except Exception:
                    print("Subscription callback error")
                    traceback.print_exc()

        # System
        if msg_type == "system":
            if msg_id == WsLinkSession.AUTH_ID:
                self.client_id = msg_result.get("clientID")
                self.unchunker.set_max_message_size(msg_result.get("maxMsgSize"))
                msg_result = self.client_id

            if pending:
                future.set_result(msg_result)

    async def listen(self):
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.CLOSE:
                print("CLOSE")
            elif msg.type == aiohttp.WSMsgType.CLOSING:
                print("CLOSING")
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                print("CLOSED")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print("ERROR")
            elif msg.type == aiohttp.WSMsgType.TEXT:
                logger.critical("wslink is not expecting text message:\n> %s", msg.data)
            if msg.type == aiohttp.WSMsgType.BINARY:
                full_message = self.unchunker.process_chunk(msg.data)
                if full_message is not None:
                    await self.on_msg_complete(full_message)

    async def auth(self, **kwargs):
        key = WsLinkSession.AUTH_ID
        resp = self.loop.create_future()
        wrapper = {
            "wslink": "1.0",
            "id": key,
            "method": "wslink.hello",
            "args": [kwargs],
            "kwargs": {},
        }

        packed_wrapper = msgpack.packb(wrapper)
        self.in_flight_rpc[key] = resp

        async with self.attachment_atomic:
            for chunk in generate_chunks(packed_wrapper, MAX_MSG_SIZE):
                if self.ws is not None:
                    await self.ws.send_bytes(chunk)

        return resp

    async def call(self, method, args=None, kwargs=None):
        self.msg_count += 1
        key = f"rpc:{self.client_id}:{self.msg_count}"
        resp = self.loop.create_future()
        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        wrapper = {
            "wslink": "1.0",
            "id": key,
            "method": method,
            "args": args,
            "kwargs": kwargs,
        }

        packed_wrapper = msgpack.packb(wrapper)
        self.in_flight_rpc[key] = resp

        async with self.attachment_atomic:
            for chunk in generate_chunks(packed_wrapper, MAX_MSG_SIZE):
                if self.ws is not None:
                    await self.ws.send_bytes(chunk)

        return resp

    def register_subscription(self, topic, callback):
        if topic not in self.subscriptions:
            self.subscriptions[topic] = [callback]
        else:
            self.subscriptions[topic].append(callback)

    def unregister_subscription(self, topic, callback):
        callbacks = self.subscriptions.get(topic, [])
        if callback in callbacks:
            callbacks.remove(callback)

        if len(callbacks) == 0 and topic in self.subscriptions:
            self.subscriptions.pop(topic)

    def clear_subscriptions(self):
        topics = list(self.subscriptions.keys())
        for topic in topics:
            self.subscriptions.pop(topic)

    async def close(self):
        if self.ws:
            await self.ws.close()


class Client:
    """
    Client implementation for driving a remote trame server with its shared state and
    trigger method calls in plain python.
    """

    def __init__(self, url=None, config=None, translator=None, hot_reload=False):
        # Network
        self._connected = ConnectionStatus.DISCONNECTED
        self._session = None
        self._url = url
        self._config = {} if config is None else config

        # fake server
        self.hot_reload = hot_reload
        self._change_callbacks = {}

        # trame state
        self._state = State(
            translator, commit_fn=self._push_state, hot_reload=hot_reload
        )

    async def connect(self, url=None, **kwargs):
        """
        Connect to the server and process messages until disconnected.

        The client is only reported as connected once authentication
        succeeded. Raises if the connection or authentication fails.
        """
        if self._connected != ConnectionStatus.DISCONNECTED:
            return
        self._connected = ConnectionStatus.CONNECTING

        config = {**self._config, **kwargs}
        if url is None:
            url = self._url

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    self._session = WsLinkSession(ws)
                    self._state.ready()
                    self._session.register_subscription(
                        "trame.state.topic", self._on_state_update
                    )
                    listen_task = asynchronous.create_task(self._session.listen())
                    try:
                        await self._wait_for_auth(listen_task, config)
                    except BaseException:
                        listen_task.cancel()
                        raise
                    self._connected = ConnectionStatus.CONNECTED
                    await listen_task
        finally:
            if self._session:
                self._session.clear_subscriptions()
                self._session = None
            self._connected = ConnectionStatus.DISCONNECTED

    async def _wait_for_auth(self, listen_task, config):
        auth_response = await self._session.auth(**config)
        await asyncio.wait(
            {auth_response, listen_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if not auth_response.done():
            auth_response.cancel()
            msg = "Connection closed before authentication completed"
            raise ConnectionError(msg)

        # Raise if authentication failed
        auth_response.result()

    async def disconnect(self):
        if self._session:
            await self._session.close()

    # -----------------------------------------------------
    # Fake server for state
    # -----------------------------------------------------

    @property
    def change(self):
        """
        Use as decorator `@server.change(key1, key2, ...)` so the decorated function
        will be called like so `_fn(**state)` when any of the listed key name
        is getting modified from either client or server.

        :param *_args: A list of variable name to monitor
        :type *_args: str
        """
        return self._state.change

    def _push_state(self, state):
        if self._session and self._session.client_id is not None:
            delta = []
            for key, value in state.items():
                if isinstance(value, dict) and "_filter" in value:
                    skip_keys = set(value.get("_filter"))
                    new_value = {}
                    for k, v in value.items():
                        if k not in skip_keys:
                            new_value[k] = v
                    delta.append({"key": key, "value": new_value})
                else:
                    delta.append({"key": key, "value": value})
            asynchronous.create_task(self._session.call("trame.state.update", [delta]))

    def _on_state_update(self, modified_state):
        with self.state:
            self.state.update(modified_state)

    # -----------------------------------------------------

    @property
    def connected(self):
        return self._connected

    @property
    def state(self):
        return self._state

    async def call_trigger(self, name, args=None, kwargs=None):
        if self._connected != ConnectionStatus.CONNECTED:
            msg = f"Client is not connected (status: {self._connected.name})"
            raise ConnectionError(msg)

        if args is None:
            args = []

        if kwargs is None:
            kwargs = {}

        response = await self._session.call("trame.trigger", [name, args, kwargs])
        return await response
