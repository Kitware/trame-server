import traceback
import aiohttp
import asyncio
import json
from trame_server.utils import asynchronous
from .state import State


def is_attach_key(value):
    return isinstance(value, str) and value.startswith("wslink_bin")


class WsLinkSession:
    CLIENT_ERROR = -32099
    AUTH_ID = "system:c0:0"

    def __init__(self, ws):
        self.loop = asyncio.get_running_loop()
        self.ws = ws
        self.msg_count = 0
        self.bin_id = 1
        self.attachments = {}
        self.subscriptions = {}
        self.client_id = None
        self.in_flight_rpc = {}
        self.in_flight_attachment = []
        self.used_attachment_keys = set()
        self.found_attachment = False

    def _clean_used_attachments(self):
        for key in self.used_attachment_keys:
            self.attachments.pop(key)

        self.used_attachment_keys.clear()

    def _bind_binary(self, msg_result, reset=False):
        if reset:
            self.found_attachment = False

        if msg_result is None:
            return None

        if len(self.attachments):
            if isinstance(msg_result, str) and msg_result in self.attachments:
                self.used_attachment_keys.add(msg_result)
                self.found_attachment = True
                return self.attachments.get(msg_result)
            elif isinstance(msg_result, dict):
                output = {}
                for key, value in msg_result.items():
                    if isinstance(value, (str, dict)):
                        output[key] = self._bind_binary(value, True)
                        if self.found_attachment:
                            output["_filter"] = msg_result.get("_filter", []) + [key]
                    elif key not in output:
                        output[key] = value

                return output

        return msg_result

    async def listen(self):
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except ValueError:
                    print("Malformed TEXT message")
                    continue

                # Notification-only message from the server - should be binary attachment header
                if "id" not in payload:
                    if payload.get("method") == "wslink.binary.attachment":
                        for key in payload.get("args", []):
                            self.attachments[key] = None
                            self.in_flight_attachment.append(key)
                    continue

                msg_id = payload.get("id")
                msg_type, msg_topic, msg_idx = msg_id.split(":")
                future = self.in_flight_rpc.get(msg_id)

                # Error
                if "error" in payload:
                    self.attachments.clear()
                    self.in_flight_attachment.clear()
                    if future:
                        future.set_exception(
                            payload.get("error", "Server error")
                        )  # May need to wrap in Exception?
                    else:
                        print("Server error:", payload.get("error"))

                    self.in_flight_rpc.pop(msg_id)
                    continue

                # Normal processing
                msg_result = payload.get("result")

                # RPC
                if msg_type == "rpc":
                    if future:
                        future.set_result(self._bind_binary(msg_result))
                        self._clean_used_attachments()

                # Publish
                if msg_type == "publish" and msg_topic in self.subscriptions:
                    event = self._bind_binary(msg_result)
                    self._clean_used_attachments()
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
                        future.set_result(self.client_id)
                    else:
                        future.set_result(msg_result)

                # Clean pending future
                if future:
                    self.in_flight_rpc.pop(msg_id)

            elif msg.type == aiohttp.WSMsgType.BINARY:
                if len(self.in_flight_attachment):
                    key = self.in_flight_attachment.pop(0)
                    self.attachments[key] = msg.data
                else:
                    raise ValueError("Attachment missing registration key")
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                print("CLOSE")
            elif msg.type == aiohttp.WSMsgType.CLOSING:
                print("CLOSING")
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                print("CLOSED")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print("ERROR")
                break

    async def auth(self, **kwargs):
        key = WsLinkSession.AUTH_ID
        resp = self.loop.create_future()
        msg = dict(
            wslink="1.0",
            id=key,
            method="wslink.hello",
            args=[kwargs],
            kwargs={},
        )
        self.in_flight_rpc[key] = resp
        await self.ws.send_str(json.dumps(msg))
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

        await self.ws.send_str(
            json.dumps(
                dict(
                    wslink="1.0",
                    id=key,
                    method=method,
                    args=args,
                    kwargs=kwargs,
                )
            )
        )

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
    Client implementation for driving a remote trame server with its shared state and trigger method calls in plain python.
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
        if self._session:
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
