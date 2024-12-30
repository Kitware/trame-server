import os
import traceback
import aiohttp
import msgpack
import logging
from wslink.chunking import generate_chunks, UnChunker
import asyncio
from trame_server.utils import asynchronous
from .state import State

MAX_MSG_SIZE = int(os.environ.get("WSLINK_MAX_MSG_SIZE", 4194304))

logger = logging.getLogger(__name__)


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
        msg_type, msg_topic, msg_idx = msg_id.split(":")
        future = self.in_flight_rpc.get(msg_id)

        # Error
        if "error" in payload:
            if future:
                future.set_exception(
                    payload.get("error", "Server error")
                )  # May need to wrap in Exception?
            else:
                print("Server error:", payload.get("error"))

            self.in_flight_rpc.pop(msg_id)
            return

        # Normal processing
        msg_result = payload.get("result")

        # RPC
        if msg_type == "rpc":
            if future:
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
                future.set_result(self.client_id)
            else:
                future.set_result(msg_result)

        # Clean pending future
        if future:
            self.in_flight_rpc.pop(msg_id)

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
        wrapper = dict(
            wslink="1.0",
            id=key,
            method="wslink.hello",
            args=[kwargs],
            kwargs={},
        )
        self.in_flight_rpc[key] = resp

        try:
            packed_wrapper = msgpack.packb(wrapper)
        except Exception:
            del wrapper["error"]["data"]
            packed_wrapper = msgpack.packb(wrapper)

        async with self.attachment_atomic:
            for chunk in generate_chunks(packed_wrapper, MAX_MSG_SIZE):
                if self.ws is not None:
                    await self.ws.send_bytes(chunk)

        return resp

    async def call(self, method, args=None, kwargs=None):
        self.msg_count += 1
        key = f"rpc:{self.client_id}:{self.msg_count}"
        resp = self.loop.create_future()
        self.in_flight_rpc[key] = resp
        if args is None:
            args = []
        if kwargs is None:
            kwargs = {}

        wrapper = dict(
            wslink="1.0",
            id=key,
            method=method,
            args=args,
            kwargs=kwargs,
        )

        try:
            packed_wrapper = msgpack.packb(wrapper)
        except Exception:
            del wrapper["error"]["data"]
            packed_wrapper = msgpack.packb(wrapper)

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
        self._connected = 0
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
        if self._connected:
            return
        self._connected = 1

        config = {**self._config, **kwargs}
        if url is None:
            url = self._url

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                self._session = WsLinkSession(ws)
                self._state.ready()
                self._session.register_subscription(
                    "trame.state.topic", self._on_state_update
                )
                self._connected = 2
                task = asynchronous.create_task(self._session.listen())
                await self._session.auth(**config)
                await task

        self._session.clear_subscriptions()
        self._session = None
        self._connected = 0

    async def diconnect(self):
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
                    delta.append(dict(key=key, value=new_value))
                else:
                    delta.append(dict(key=key, value=value))
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
        if args is None:
            args = []

        if kwargs is None:
            kwargs = {}

        response = await self._session.call("trame.trigger", [name, args, kwargs])
        return await response
