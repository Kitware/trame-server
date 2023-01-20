import os
import inspect

from wslink import server
from wslink import register as exportRpc
from wslink.websocket import ServerProtocol

from trame_server.utils import logger, clean_state
from trame_server.state import TRAME_NON_INIT_VALUE


class CoreServer(ServerProtocol):
    authentication_token = "wslink-secret"
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

    @staticmethod
    def configure(args):
        if args.authKeyFile:
            with open(args.authKeyFile) as key_file:
                CoreServer.authentication_token = key_file.read().strip()
        else:
            CoreServer.authentication_token = args.authKey

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

    def initialize(self):  # Called by wslink
        self.rpcMethods = {}
        self.server = CoreServer.server
        self.server._root_protocol = self
        self._clients_state = {}

        for configure in self.server._protocols_to_configure:
            configure(self)

        self.updateSecret(CoreServer.authentication_token)

    def set_server(self, _server):
        self.server._server = _server
        if self.server.controller.on_server_bind.exists():
            # Hack - use internal of aiohttp to rework routes order
            # FIXME: WON'T WORK with a different backend
            server_routes = _server.app.router._resources
            wslink_routes = list(server_routes)
            server_routes.clear()
            self.server.controller.on_server_bind(_server)
            server_routes.extend(wslink_routes)

    def port_callback(self, port_used):
        self.server._running_port = port_used
        if self.server._running_stage < 2:
            self.server._running_stage = 2
            self.server.state.server_ready()
            if self.server.controller.on_server_ready.exists():
                self.server.controller.on_server_ready(**self.server.state.to_dict())

            # Mark the server as ready
            if not self.server.ready.done():
                self.server.ready.set_result(True)

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
    # RPCs
    # ---------------------------------------------------------------

    @exportRpc("trame.lifecycle.update")
    def life_cycle_update(self, name):
        _fn = self.server.controller[f"on_{name}"]
        if _fn.exists():
            _fn()

    # ---------------------------------------------------------------

    @exportRpc("trame.error.client")
    def js_error(self, message):
        print(f" JS Error => {message}")

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
            if name in self.server._triggers:
                result = self.server._triggers[name](*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            else:
                print(f"Trigger {name} seems to be missing")

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
