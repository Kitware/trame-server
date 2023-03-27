import asyncio
import inspect
import logging
import os
import sys

from . import utils

from .state import State
from .controller import Controller
from .ui import VirtualNodeManager
from .protocol import CoreServer
from .utils.argument_parser import ArgumentParser


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

    def __init__(self, name="trame", vn_constructor=None, **options):
        # Core internal variables
        self._server = None
        self._running_port = 0
        self._running_stage = 0  # 0: off / 1: pending / 2: running
        self._running_future = None
        self._name = name
        self._www = None
        self._options = options
        self._client_type = None

        # Controller
        self._controller = Controller(self)

        # UI
        self._ui = VirtualNodeManager(self, vn_constructor)

        # HTTP server
        self.serve = {}

        # @change
        self._change_callbacks = {}

        # @trigger
        self._triggers = {}
        self._triggers_fn2name = {}
        self._triggers_name_id = 0

        # CLI argument handling
        self._cli_parser = None

        # modules
        self._loaded_modules = set()

        # protocols to register
        self._root_protocol = None
        self._protocols_to_configure = []

        # Shared state + reserve internal keys
        self._state = State(self)
        for key in ["scripts", "module_scripts", "styles", "vue_use", "mousetrap"]:
            self._state[f"trame__{key}"] = []
        self._state.trame__client_only = ["trame__busy"]
        self._state.trame__busy = 1
        self._state.trame__favicon = None
        self._state.trame__title = "Trame"

        # ENV variable mapping settings
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

        # Initialize hot reload
        self.hot_reload = "--hot-reload" in sys.argv or bool(
            os.getenv("TRAME_HOT_RELOAD", False)
        )

    # -------------------------------------------------------------------------
    # State management helpers
    # -------------------------------------------------------------------------

    def _push_state(self, state):
        if self.protocol:
            self.protocol.push_state_change(state)

    # -------------------------------------------------------------------------
    # Initialization helper
    # -------------------------------------------------------------------------

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

    def js_call(self, ref: str = None, method: str = None, *args):
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
                    }
                ]
            )

    # -------------------------------------------------------------------------
    # Annotations
    # -------------------------------------------------------------------------

    def change(self, *_args, **_kwargs):
        """
        Use as decorator `@server.change(key1, key2, ...)` so the decorated function
        will be called like so `_fn(**state)` when any of the listed key name
        is getting modified from either client or server.

        :param *_args: A list of variable name to monitor
        :type *_args: str
        """

        def register_change_callback(func):
            for name in _args:
                if name not in self._change_callbacks:
                    self._change_callbacks[name] = []

                self._change_callbacks[name].append(func)
            return func

        return register_change_callback

    # -------------------------------------------------------------------------

    def trigger(self, name):
        """
        Use as decorator `@server.trigger(name)` so the decorated function
        will be able to be called from the client by doing `click="trigger(name)"`.

        :param name: A name to use for that trigger
        :type name: str
        """

        def register_trigger(func):
            self._triggers[name] = func
            self._triggers_fn2name[func] = name
            return func

        return register_trigger

    # -------------------------------------------------------------------------
    # From a function get its trigger name and register it if need be
    # -------------------------------------------------------------------------

    def trigger_name(self, fn):
        """
        Given a function this method will register a trigger and returned its name.
        If manually registered, the given name at the time will be returned.

        :return: The trigger name for that function
        :rtype: str
        """
        if fn in self._triggers_fn2name:
            return self._triggers_fn2name[fn]

        self._triggers_name_id += 1
        name = f"trigger__{self._triggers_name_id}"
        self.trigger(name)(fn)
        return name

    # -------------------------------------------------------------------------
    # App properties
    # -------------------------------------------------------------------------

    @property
    def name(self):
        """Name of server"""
        return self._name

    @property
    def options(self):
        """Server options provided at instantiation time"""
        return self._options

    @property
    def client_type(self):
        """Specify the client type. Either 'vue2' or 'vue3' for now."""
        if self._client_type is None:
            return "vue2"  # default
        return self._client_type

    @client_type.setter
    def client_type(self, value):
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
    def state(self):
        """
        :return: The server shared state
        :rtype: trame_server.state.State
        """
        return self._state

    @property
    def controller(self):
        """
        :return: The server controller
        :rtype: trame_server.controller.Controller
        """
        return self._controller

    @property
    def ui(self):
        """
        :return: The server VirtualNode manager
        :rtype: trame_server.ui.VirtualNodeManager
        """
        return self._ui

    @property
    def running(self):
        """Return True if the server is currently starting or running."""
        return self._running_stage > 1

    @property
    def ready(self):
        """Return a future that will resolve once the server is ready"""
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

    # -------------------------------------------------------------------------

    def add_protocol_to_configure(self, configure_protocol_fn):
        """
        Register function that will be called with a wslink.ServerProtocol
        when the server start and is ready for registering new wslink.Protocol.

        :param configure_protocol_fn: A function to be called later with a
                                      wslink.ServerProtocol as argument.
        """
        self._protocols_to_configure.append(configure_protocol_fn)

    @property
    def protocol(self):
        """Return the server root protocol"""
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

    # -------------------------------------------------------------------------
    # Server handling (start/stop/port)
    # -------------------------------------------------------------------------

    def start(
        self,
        port: int = None,
        thread: bool = False,
        open_browser: bool = True,
        show_connection_info: bool = True,
        disable_logging: bool = False,
        backend: str = "aiohttp",
        exec_mode: str = "main",
        timeout: int = None,
        host: str = None,
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
        if self._running_stage:
            return

        # Try to bind client if none were added
        if self._www is None:
            from trame_client import module

            self.enable_module(module)

        # Trigger on_server_start life cycle callback
        if self.controller.on_server_start.exists():
            self.controller.on_server_start(self)

        CoreServer.bind_server(self)
        options = self.cli.parse_known_args()[0]

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

    async def stop(self):
        """Coroutine for stopping the server"""
        if self._running_stage:
            await self._server.stop()
            self._running_future = None

    @property
    def port(self):
        """Once started, you can retrieve the port used"""
        return self._running_port
