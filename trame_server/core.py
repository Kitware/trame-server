from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
from typing import Literal

from . import utils
from .http import HttpHeader
from .controller import Controller
from .protocol import CoreServer
from .state import State
from .ui import VirtualNodeManager
from .utils import share
from .utils.argument_parser import ArgumentParser
from .utils.namespace import Translator

logger = logging.getLogger(__name__)

ClientType = Literal["vue2", "vue3"]
BackendType = Literal["aiohttp", "generic", "tornado", "jupyter"]
ExecModeType = Literal["main", "desktop", "task", "coroutine"]

DEFAULT_CLIENT_TYPE: ClientType = "vue3"


def set_default_client_type(value: ClientType) -> None:
    global DEFAULT_CLIENT_TYPE
    DEFAULT_CLIENT_TYPE = value


class Server:
    """
    Server implementation for trame.
    This is the core object that manage client/server communication but also
    holds a state and controller instance.
    With trame a server instance should be retrieved by using **trame.app.get_server()**

    Known options:
      - log_network: False (path to log file)
      - ws_max_msg_size: 10000000 (bytes)
      - ws_heart_beat: 30
      - desktop_debug: False

    :param name: A name identifier for a given server
    :type name: str, optional (default: trame)

    :param **options: Gather any keyword arguments into options
    :type options: Dict
    """

    def __init__(
        self,
        name="trame",
        vn_constructor=None,
        translator=None,
        parent_server=None,
        **options,
    ) -> None:
        # Core internal variables
        self._parent_server = parent_server
        self._translator = translator if translator else Translator()
        self._name = share(parent_server, "_name", name)
        self._options = share(parent_server, "_options", options)
        self._client_type = share(parent_server, "_client_type", None)
        self._http_header = share(parent_server, "_http_header", HttpHeader())

        # use parent_server instead of local version
        self._server = None
        self._running_stage = 0  # 0: off / 1: pending / 2: running
        self._running_port = 0
        self._running_future = None
        self._www = None
        self.serve = {}  # HTTP static endpoints
        self._loaded_modules = set()
        self._cli_parser = None
        self._root_protocol = None
        self._protocols_to_configure = []

        # ENV variable mapping settings
        self.hot_reload = "--hot-reload" in sys.argv or bool(
            os.getenv("TRAME_HOT_RELOAD", False)
        )
        if parent_server is None:
            self._options["log_network"] = self._options.get(
                "log_network", os.environ.get("TRAME_LOG_NETWORK", False)
            )
            self._options["ws_max_msg_size"] = self._options.get(
                "ws_max_msg_size", os.environ.get("TRAME_WS_MAX_MSG_SIZE", 10000000)
            )
            self._options["ws_heart_beat"] = self._options.get(
                "ws_heart_beat", os.environ.get("TRAME_WS_HEART_BEAT", 30)
            )
            self._options["desktop_debug"] = self._options.get(
                "desktop_debug", os.environ.get("TRAME_DESKTOP_DEBUG", False)
            )
            # reset default wslink startup message
            os.environ["WSLINK_READY_MSG"] = ""

        # Shared state + reserve internal keys
        if parent_server is None:
            self._state = State(
                self.translator, commit_fn=self._push_state, hot_reload=self.hot_reload
            )
            for key in ["scripts", "module_scripts", "styles", "vue_use", "mousetrap"]:
                self._state[f"trame__{key}"] = []
            self._state.trame__client_only = ["trame__busy"]
            self._state.trame__busy = 1
            self._state.trame__favicon = None
            self._state.trame__title = "Trame"
        else:
            self._state = State(
                self.translator,
                internal=parent_server._state,
                commit_fn=self._push_state,
                hot_reload=self.hot_reload,
            )

        # Controller
        if parent_server is None:
            self._controller = Controller(self.translator, hot_reload=self.hot_reload)
        else:
            self._controller = Controller(
                self.translator,
                internal=parent_server._controller,
                hot_reload=self.hot_reload,
            )

        # Server only context
        if parent_server is None:
            self._context = State(self.translator, hot_reload=self.hot_reload)
        else:
            self._context = State(
                self.translator,
                internal=parent_server._context,
                hot_reload=self.hot_reload,
            )

        # UI (FIXME): use for translator
        self._ui = share(parent_server, "_ui", VirtualNodeManager(self, vn_constructor))

    def create_child_server(self, translator=None, prefix=None) -> Server:
        translator = translator if translator else Translator(prefix=prefix)
        return Server(translator=translator, parent_server=self)

    # -------------------------------------------------------------------------
    # State management helpers
    # -------------------------------------------------------------------------

    def _push_state(self, state):
        if self.protocol:
            self.protocol.push_state_change(state)

    # -------------------------------------------------------------------------
    # Initialization helper
    # -------------------------------------------------------------------------

    @property
    def http_headers(self):
        """Return http header helper so they can be applied before the server start."""
        return self._http_header

    def enable_module(self, module, **kwargs):
        """
        Expend server using a module definition which can be used to serve custom
        client code or assets, load/initialize resources (js, css, vue),
        register custom protocols and even execute custom code.

        Any previously seem module will be automatically skipped.

        The attributes that are getting processed in a module are the following:
          - setup(server, **kwargs): Function called first
          - scripts = []           : List all JavaScript URL that should be loaded
          - module_scripts = []    : List all JavaScript URL as type=module to load
          - styles  = []           : List all CSS URL that should be loaded
          - vue_use = ['libName', ('libName2', { **options })]: List Vue plugin to load
          - state = {}             : Set of variable to add to state
          - server = { data: '/path/on/fs' }: Set of endpoints to server static content
          - www = '/path/on/fs'    : Path served as main web content

        :param module: A module to enable or a dict()
        :param kwargs: Any optional parameters needed for your module setup() function.
        """
        if self.root_server != self:
            self.root_server.enable_module(module, **kwargs)
            return

        # Make sure definitions is a dict while skipping already loaded module
        definitions = module
        if isinstance(definitions, dict):
            definitions = module
        elif definitions in self._loaded_modules:
            return
        else:
            self._loaded_modules.add(definitions)
            definitions = definitions.__dict__

        if "setup" in definitions:
            definitions["setup"](self, **kwargs)

        for key in ["scripts", "module_scripts", "styles", "vue_use"]:
            if key in definitions:
                self.state[f"trame__{key}"] += definitions[key]

        if "state" in definitions:
            self.state.update(definitions["state"])

        if "serve" in definitions:
            self.serve.update(definitions["serve"])

        if "www" in definitions:
            self._www = definitions["www"]

        # Reduce vue_use to merge options
        utils.reduce_vue_use(self.state)

    # -------------------------------------------------------------------------
    # Call methods
    # -------------------------------------------------------------------------

    def js_call(self, ref: str | None = None, method: str | None = None, *args):
        """
        Python call method on JS element.

        :param ref: ref name of the widget element
        :type ref: str

        :param method: name of the method that should be called
        :type method: str

        :param *args: set of parameters needed for the function
        """
        if self.protocol:
            self.protocol.push_actions(
                [
                    {
                        "type": "method",
                        "ref": ref,
                        "method": method,
                        "args": list(args),
                    },
                ],
            )

    # -------------------------------------------------------------------------
    # Annotations
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------

    @property
    def trigger(self):
        """
        Use as decorator `@server.trigger(name)` so the decorated function
        will be able to be called from the client by doing `click="trigger(name)"`.

        :param name: A name to use for that trigger
        :type name: str
        """
        return self._controller.trigger

    # -------------------------------------------------------------------------
    # From a function get its trigger name and register it if need be
    # -------------------------------------------------------------------------

    @property
    def trigger_name(self):
        """
        Given a function this method will register a trigger and returned its name.
        If manually registered, the given name at the time will be returned.

        :return: The trigger name for that function
        :rtype: str
        """
        return self._controller.trigger_name

    # -------------------------------------------------------------------------
    # App properties
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Name of server"""
        return self._name

    @property
    def root_server(self) -> Server:
        """Root server to start"""
        if self._parent_server:
            return self._parent_server.root_server
        return self

    @property
    def translator(self):
        """Translator of the server"""
        return self._translator

    @property
    def options(self):
        """Server options provided at instantiation time"""
        return self._options

    @property
    def client_type(self) -> ClientType:
        """Specify the client type. Either 'vue2' or 'vue3' for now."""
        if self._client_type is None:
            return DEFAULT_CLIENT_TYPE  # default
        return self._client_type

    @client_type.setter
    def client_type(self, value: ClientType) -> None:
        """Should only be called once before any widget initialization"""
        if self._client_type is None:
            self._client_type = value

        if self.client_type != value:
            raise TypeError(
                f"""
                Trying to switch client_type from {self._client_type} to {value}.
                The client_type can only be set once.
            """
            )

    @property
    def cli(self):
        """argparse parser"""
        if self.root_server != self:
            return self.root_server.cli

        if self._cli_parser:
            return self._cli_parser

        self._cli_parser = ArgumentParser(description="Kitware trame")

        # Trame specific args
        self._cli_parser.add_argument(
            "--server",
            help="Prevent your browser from opening at startup",
            action="store_true",
        )
        self._cli_parser.add_argument(
            "--banner",
            help="Print trame banner",
            action="store_true",
        )
        self._cli_parser.add_argument(
            "--app",
            help="Use OS built-in browser",
            action="store_true",
        )
        self._cli_parser.add_argument(
            "--no-http",
            help="Do not serve anything over http",
            dest="no_http",
            action="store_true",
        )
        self._cli_parser.add_argument(
            "--authKeyFile",
            help="""Path to a File that contains the Authentication key for clients
                    to connect to the WebSocket.
                    This takes precedence over '-a, --authKey' from wslink.""",
        )
        self._cli_parser.add_argument(
            "--hot-reload",
            help="""Automatically reload state/controller callback functions for every
                    function call. This allows live editing of the functions. Functions
                    located in the site-packages directories are skipped.""",
            action="store_true",
        )
        self._cli_parser.add_argument(
            "--trame-args",
            help="""If specified, trame will ignore all other arguments, and only the contents
                    of the `--trame-args` will be used. For example:
                    `--trame-args="-p 8081 --server"`. Alternatively, the environment variable
                    `TRAME_ARGS` may be set instead.""",
        )

        CoreServer.add_arguments(self._cli_parser)

        return self._cli_parser

    @property
    def state(self) -> State:
        """
        :return: The server shared state
        :rtype: trame_server.state.State
        """
        return self._state

    @property
    def context(self) -> State:
        """
        The server-only context (not shared with the client).

        :return: The server context state
        :rtype: trame_server.state.State
        """
        return self._context

    @property
    def controller(self) -> Controller:
        """
        :return: The server controller
        :rtype: trame_server.controller.Controller
        """
        return self._controller

    @property
    def ui(self) -> VirtualNodeManager:
        """
        :return: The server VirtualNode manager
        :rtype: trame_server.ui.VirtualNodeManager
        """
        return self._ui

    @property
    def running(self) -> bool:
        """Return True if the server is currently starting or running."""
        if self.root_server != self:
            return self.root_server.running

        return self._running_stage > 1

    @property
    def network_completion(self):
        """Return a future to await if you want to ensure that any pending network call
        have been issued before locking the server"""
        return asyncio.ensure_future(self.context.network_monitor.completion())

    @property
    def ready(self):
        """Return a future that will resolve once the server is ready"""
        if self.root_server != self:
            return self.root_server.ready

        if self._running_future is None:
            self._running_future = asyncio.get_running_loop().create_future()

        return self._running_future

    # -------------------------------------------------------------------------
    # API for network handling
    # -------------------------------------------------------------------------

    def get_server_state(self):
        """Return the current server state"""
        state = {
            "name": self._name,
            "state": self.state.initial,
        }
        return state

    def clear_state_client_cache(self, *state_names):
        protocol = self.protocol
        if protocol:
            protocol.clear_state_client_cache(*state_names)

    # -------------------------------------------------------------------------

    def add_protocol_to_configure(self, configure_protocol_fn):
        """
        Register function that will be called with a wslink.ServerProtocol
        when the server start and is ready for registering new wslink.Protocol.

        :param configure_protocol_fn: A function to be called later with a
                                      wslink.ServerProtocol as argument.
        """
        if self.root_server != self:
            self.root_server.add_protocol_to_configure(configure_protocol_fn)
            return

        self._protocols_to_configure.append(configure_protocol_fn)

    @property
    def protocol(self):
        """Return the server root protocol"""
        if self.root_server != self:
            return self.root_server.protocol

        return self._root_protocol

    # -------------------------------------------------------------------------

    def protocol_call(self, method, *args, **kwargs):
        """
        Call a registered protocol method

        :param method: Method registration name
        :type method: str
        :param *args: Set of args to use for that method call
        :param **kwargs: Set of keyword arguments to use for that method call
        :return: transparently return what the called function returns
        """
        if self.protocol:
            pair = self.protocol.getRPCMethod(method)
            if pair:
                obj, func = pair
                return func(obj, *args, **kwargs)

    def force_state_push(self, *key_names):
        """
        Should only be needed when client corrupted its data and need the server need to send it again.

        :param *args: Set of key names to be send again to the client.
        """
        self.protocol_call(
            "trame.force.push", *[self._translator.translate_key(k) for k in key_names]
        )

    # -------------------------------------------------------------------------
    # Server handling (start/stop/port)
    # -------------------------------------------------------------------------

    def start(
        self,
        port: int | None = None,
        thread: bool = False,
        open_browser: bool | None = None,
        show_connection_info: bool = True,
        disable_logging: bool = False,
        backend: BackendType | None = None,
        exec_mode: ExecModeType = "main",
        timeout: int | None = None,
        host: str | None = None,
        **kwargs,
    ):
        """
        Start the server by listening to the provided port or using the
        `--port, -p` command line argument.
        If the server is already starting or started, any further call will be skipped.

        When the exec_mode="main" or "desktop", the method will be blocking.
        If exec_mode="task", the method will return a scheduled task.
        If exec_mode="coroutine", the method will return a coroutine which
        will need to be scheduled by the user.

        :param port: A port number to listen to. When 0 is provided
                     the system will use a random open port.
        :param thread: If the server run in a thread which means
                       we should disable interuption listeners
        :param open_browser: Should we open the system browser with app url.
                             Using the `--server` command line argument is
                             similar to setting it to False.
        :param show_connection_info: Should we print connection URL at startup?
        :param disable_logging: Ask wslink to disable logging
        :param backend: aiohttp by default but could be generic or tornado.
                        This can also be set with the environment variable ``TRAME_BACKEND``.
                        Defaults to ``'aiohttp'``.
        :param exec_mode: main/desktop/task/coroutine
                          specify how the start function should work
        :param timeout: How much second should we wait before automatically
                        stopping the server when no client is connected.
                        Setting it to 0 will disable such auto-shutdown.
        :param host: The hostname used to bind the server. This can also be
                     set with the environment variable ``TRAME_DEFAULT_HOST``.
                     Defaults to ``'localhost'``.
        :param **kwargs: Keyword arguments for capturing optional parameters
                         for wslink server and/or desktop browser
        """
        if self.root_server != self:
            self.root_server.start(
                port=port,
                thread=thread,
                open_browser=open_browser,
                show_connection_info=show_connection_info,
                disable_logging=disable_logging,
                backend=backend,
                exec_mode=exec_mode,
                timeout=timeout,
                host=host,
                **kwargs,
            )
            return

        if self._running_stage:
            return

        # Try to bind client if none were added
        if self._www is None:
            from trame_client import module

            self.enable_module(module)

        # Apply any header change needed
        self._http_header.apply()

        # Trigger on_server_start life cycle callback
        if self.controller.on_server_start.exists():
            self.controller.on_server_start(self)

        CoreServer.bind_server(self)
        options = self.cli.parse_known_args()[0]

        if backend is None:
            backend = os.environ.get("TRAME_BACKEND", "aiohttp")

        if open_browser is None:
            open_browser = not os.environ.get("TRAME_SERVER", False)

        if options.host == "localhost":
            if host is None:
                host = os.environ.get("TRAME_DEFAULT_HOST", "localhost")
            options.host = host

        if timeout is not None:
            options.timeout = timeout

        if port is not None:
            options.port = port

        if not options.content:
            options.content = self._www

        if thread:
            options.nosignalhandlers = True

        if options.banner:
            from .utils.banner import print_banner

            self.controller.on_server_ready.add(print_banner)

        if options.app:
            exec_mode = "desktop"

        if exec_mode == "desktop":
            from .utils.desktop import start_browser

            options.port = 0
            exec_mode, show_connection_info, open_browser = "main", False, False
            self.controller.on_server_ready.add(
                lambda **_: start_browser(self, **kwargs)
            )

        # Allow for older wslink versions where this was not an attribute
        reverse_url = getattr(options, "reverse_url", None)

        if not reverse_url and show_connection_info and exec_mode != "task":
            from .utils.server import print_informations

            self.controller.on_server_ready.add(
                lambda **kwargs: print_informations(self)
            )

        if (
            not reverse_url
            and open_browser
            and exec_mode != "task"
            and not options.server
        ):
            from .utils.browser import open_browser

            self.controller.on_server_ready.add(lambda **kwargs: open_browser(self))

        if len(self.serve):
            endpoints = []
            for key in self.serve:
                value = self.serve[key]
                if isinstance(value, (list, tuple)):
                    # tuple are use to describe sync loading (affect client)
                    endpoints.append(f"{key}={value[0]}")
                else:
                    endpoints.append(f"{key}={value}")
            options.fsEndpoints = "|".join(endpoints)

        # Reset http delivery
        if options.no_http:
            options.content = ""
            options.fsEndpoints = ""

        self._server_options = options
        CoreServer.configure(options)

        self._running_stage = 1
        task = CoreServer.server_start(
            options,
            **{  # Do a proper merging/override
                **kwargs,
                "disableLogging": disable_logging,
                "backend": backend,
                "exec_mode": exec_mode,
            },
        )

        # Manage exit life cycle unless coroutine
        if exec_mode == "main":
            self._running_stage = 0
            if self.controller.on_server_exited.exists():
                loop = asyncio.get_event_loop()
                for exit_task in self.controller.on_server_exited(
                    **self.state.to_dict()
                ):
                    if inspect.isawaitable(exit_task):
                        loop.run_until_complete(exit_task)
                    elif callable(exit_task):
                        result = exit_task()
                        if inspect.isawaitable(result):
                            loop.run_until_complete(result)
        elif hasattr(task, "add_done_callback"):

            def on_done(task: asyncio.Task) -> None:
                try:
                    task.result()
                    self._running_stage = 0
                    if self.controller.on_server_exited.exists():
                        self.controller.on_server_exited(**self.state.to_dict())
                except asyncio.CancelledError:
                    pass  # Task cancellation should not be logged as an error.
                except Exception:  # pylint: disable=broad-except
                    logging.exception("Exception raised by task = %r", task)

            task.add_done_callback(on_done)

        return task

    async def stop(self) -> None:
        """Coroutine for stopping the server"""
        if self.root_server != self:
            await self.root_server.stop()
        elif self._running_stage:
            await self._server.stop()
            self._running_future = None

    @property
    def port(self) -> int:
        """Once started, you can retrieve the port used"""
        if self.root_server != self:
            return self.root_server.port

        return self._running_port

    @property
    def server_options(self):
        """Once started, you can retrieve the server options used"""
        return self._server_options
