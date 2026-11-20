import inspect
import logging
import os

from trame_common.utils import profiler
from wslink import register as exportRpc
from wslink import server
from wslink.websocket import ServerProtocol

from trame_server import auth
from trame_server.auth import aiohttp as auth_aiohttp
from trame_server.state import TRAME_NON_INIT_VALUE
from trame_server.utils import clean_state, logger

# 'logger' is the network exchange logger (--log-network)
log = logging.getLogger(__name__)


# wslink's default value for '--authKey'
DEFAULT_AUTH_KEY = auth.DEFAULT_SECRET


class CoreServer(ServerProtocol):
    authentication_token = DEFAULT_AUTH_KEY
    server = None

    # ---------------------------------------------------------------
    # Static methods
    # ---------------------------------------------------------------

    @staticmethod
    def bind_server(server):
        logger.initialize_logger(server.options)
        CoreServer.server = server

        # Forward options to wslink
        os.environ["WSLINK_MAX_MSG_SIZE"] = str(server.options["ws_max_msg_size"])
        os.environ["WSLINK_HEART_BEAT"] = str(server.options["ws_heart_beat"])

    @staticmethod
    def add_arguments(parser):
        server.add_arguments(parser)
        for action in parser._actions:
            if "--authKey" in action.option_strings:
                action.help = f"""Authentication key for clients to connect to the
                    WebSocket. '{auth.AUTO_SECRET}' generates a random key on every
                    start, given to the browser as a '?{auth.SECRET_PARAM}=...' URL
                    parameter. Defaults to wslink's well-known key."""

    @staticmethod
    def configure(args):
        """
        Resolve the WebSocket secret from the parsed CLI args and return it.

        Precedence: ``--authKeyFile``, then ``--authKey`` (``auto`` generates a
        new random secret on every call), otherwise wslink's default secret.
        """
        secret = auth.resolve_secret(
            getattr(args, "authKey", None), getattr(args, "authKeyFile", None)
        )
        # Last resolved secret, for code still reading it: each server's protocol
        # holds its own in `secret`
        CoreServer.authentication_token = secret
        return secret

    @staticmethod
    def server_start(
        options,
        disableLogging=False,
        backend="aiohttp",
        exec_mode="main",
        **kwargs,
    ):
        # NOTE: **kwargs to wslink's start_webserver are currently unused
        return server.start_webserver(
            options=options,
            protocol=CoreServer,
            disableLogging=disableLogging,
            backend=backend,
            exec_mode=exec_mode,
            **kwargs,
        )

    @staticmethod
    def server_stop():
        server.stop_webserver()

    # ---------------------------------------------------------------
    # Server
    # ---------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Profile network using the monitor
        self._network_timer = profiler.Timer("trame.network")
        self.network_monitor.add_listener(
            self._network_timer.on_start,
            self._network_timer.on_end,
        )

    def initialize(self):  # Called by wslink
        self.rpcMethods = {}
        self.server = CoreServer.server
        self.server._root_protocol = self
        self.server.context.network_monitor = self.network_monitor
        self._clients_state = {}

        for configure in self.server._protocols_to_configure:
            configure(self)

        # The secret this server started with. From now on `self.secret` is the
        # only one checked: updateSecret() changes what is accepted
        options = self.server.server_options
        self.updateSecret(
            getattr(options, "authKey", None) or CoreServer.authentication_token
        )
        self._cookie_clients = set()

    def set_server(self, _server):
        self.server._server = _server
        # Cookie on page responses: aiohttp only, other backends use the secret
        auth_aiohttp.mount(_server, lambda: self.secret, lambda: self.server.port)
        if self.server.controller.on_server_bind.exists():
            # wslink registers its static routes on start, so routes added
            # here take precedence over them
            self.server.controller.on_server_bind(_server)

    def port_callback(self, port_used):
        self.server._running_port = port_used
        if self.server._running_stage < 2:
            self.server._running_stage = 2
            self.server.state.ready()
            self.server.context.ready()

            # Add on_server_exception
            self.server.protocol.log_emitter.add_event_listener(
                "exception", self.server.controller.on_exception.enable_empty()
            )

            # Trigger on_server_ready
            if self.server.controller.on_server_ready.exists():
                self.server.controller.on_server_ready(**self.server.state.to_dict())

            # Mark the server as ready
            if not self.server.ready.done():
                self.server.ready.set_result(True)

    # ---------------------------------------------------------------
    # Authentication (called by wslink)
    # ---------------------------------------------------------------

    def onConnect(self, request, client_id):
        # Only aiohttp gives the upgrade request: tornado and jupyter go through
        # wslink's generic backend, which gives a dict without headers
        headers = getattr(request, "headers", None)
        if headers is not None and auth.check_cookie(
            self.secret, headers, self.server.port
        ):
            self._cookie_clients.add(client_id)

    def onClose(self, client_id):
        self._cookie_clients.discard(client_id)

    async def validateToken(self, token, client_id):
        """Accept the secret, or any token from a client whose connection request
        carried a valid cookie from the app's own pages."""
        return client_id in self._cookie_clients or auth.check_secret(
            self.secret, token
        )

    # ---------------------------------------------------------------

    def getRPCMethod(self, name):
        if len(self.rpcMethods) == 0:

            def is_method(x):
                return inspect.ismethod(x) or inspect.isfunction(x)

            for protocolObject in self.getLinkProtocols():
                for k in inspect.getmembers(protocolObject.__class__, is_method):
                    proc = k[1]
                    if "_wslinkuris" in proc.__dict__:
                        uri_info = proc.__dict__["_wslinkuris"][0]
                        if "uri" in uri_info:
                            uri = uri_info["uri"]
                            self.rpcMethods[uri] = (protocolObject, proc)

        if name in self.rpcMethods:
            return self.rpcMethods[name]

        return None

    # ---------------------------------------------------------------
    # Publish
    # ---------------------------------------------------------------

    def push_state_change(self, modified_state, skip_last_active_client=False):
        ok, str_values = clean_state(modified_state)
        # Only send changes
        state_to_send = {}
        for key, value in ok.items():
            prev_str = self._clients_state.get(key, TRAME_NON_INIT_VALUE)
            new_str = str_values.get(key, TRAME_NON_INIT_VALUE)
            if prev_str != new_str:
                state_to_send[key] = value

        # Log and send state
        if state_to_send:
            logger.state_s2c(state_to_send)
            self.publish(
                "trame.state.topic",
                state_to_send,
                skip_last_active_client=skip_last_active_client,
            )

        # Keep track of last push
        self._clients_state.update(str_values)

    # ---------------------------------------------------------------

    def push_actions(self, actions):
        logger.action_s2c(actions)
        self.publish("trame.actions.topic", actions)

    # ---------------------------------------------------------------
    # Internal RPCs
    # ---------------------------------------------------------------

    def clear_state_client_cache(self, *keys):
        for k in keys:
            self._clients_state.pop(k, None)

    # ---------------------------------------------------------------
    # RPCs
    # ---------------------------------------------------------------

    @exportRpc("trame.force.push")
    def force_push_state(self, *keys):
        state_to_send = {key: self.server.state[key] for key in keys}
        if state_to_send:
            self.publish(
                "trame.state.topic",
                state_to_send,
                skip_last_active_client=False,
            )

    # ---------------------------------------------------------------

    @exportRpc("trame.lifecycle.update")
    def life_cycle_update(self, name):
        _fn = self.server.controller[f"on_{name}"]
        if _fn.exists():
            _fn()

    # ---------------------------------------------------------------

    @exportRpc("trame.error.client")
    def js_error(self, message):
        if self.server.controller.on_error.exists():
            self.server.controller.on_error(message)
        else:
            log.error("JS Error => %s", message)

    # ---------------------------------------------------------------

    @exportRpc("trame.state.get")
    def get_server_state(self):
        server_state = self.server.get_server_state()
        ok, _ = clean_state(server_state.get("state", {}))
        state_to_send = {**server_state, "state": ok}
        logger.initial_state(state_to_send)
        return state_to_send

    # ---------------------------------------------------------------

    @exportRpc("trame.trigger")
    async def trigger(self, name, args, kwargs):
        logger.action_c2s({"name": name, "args": args, "kwargs": kwargs})
        with self.server.state:
            fn = self.server.controller.trigger_fn(name)
            if fn:
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            log.warning("Trigger %s seems to be missing", name)

        return None

    # ---------------------------------------------------------------

    @exportRpc("trame.state.update")
    def update_state(self, changes):
        logger.state_c2s(changes)

        with self.server.state:
            client_state = {}
            for change in changes:
                client_state[change["key"]] = change.get("value")

            # Push to other clients (collaboration) before flush
            self.push_state_change(client_state, skip_last_active_client=True)

            # Update server state
            self.server.state.update(client_state)
