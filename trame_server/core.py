import os
import argparse
import shutil
import asyncio
import logging

from . import utils

from .state import State
from .controller import Controller
from .protocol import CoreServer


class Server:
    """Server class

    Docstring
    """

    def __init__(self, name="trame", **options):
        # Core internal variables
        self._server = None
        self._running_port = 0
        self._running_stage = 0  # 0: off / 1: pending / 2: running
        self._name = name
        self._www = None
        self._options = options

        # Controller
        self.controller = Controller(self.trigger, self.trigger_name)

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
        self.state = State(self)
        for key in ["scripts", "styles", "vue_use", "mousetrap"]:
            self.state[f"trame__{key}"] = []
        self.state.trame__client_only = ["trame__busy"]
        self.state.trame__busy = 1
        self.state.trame__favicon = None
        self.state.trame__title = "Trame"

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

    # -------------------------------------------------------------------------
    # State management helpers
    # -------------------------------------------------------------------------

    def _push_state(self, state):
        if self.protocol:
            self.protocol.push_state_change(utils.clean_state(state))

    # -------------------------------------------------------------------------
    # Initialization helper
    # -------------------------------------------------------------------------

    def enable_module(self, module, **kwargs):
        if module in self._loaded_modules:
            return

        if "setup" in module.__dict__:
            module.setup(self, **kwargs)

        for key in ["scripts", "styles", "vue_use"]:
            if key in module.__dict__:
                self.state[f"trame__{key}"] += module.__dict__[key]

        if "state" in module.__dict__:
            self.state.update(module.state)

        if "serve" in module.__dict__:
            self.serve.update(module.serve)

        if "www" in module.__dict__:
            self._www = module.www

        self._loaded_modules.add(module)

    # -------------------------------------------------------------------------
    # Call methods
    # -------------------------------------------------------------------------

    def js_call(self, ref=None, method=None, *args):
        """Python call method on JS element"""
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
        Use as decorator `@server.change(key1, key2, ...)`
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
        Use as decorator `@server.trigger(name)`
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
        return self._name

    @property
    def options(self):
        return self._options

    @property
    def cli(self):
        if self._cli_parser:
            return self._cli_parser

        self._cli_parser = argparse.ArgumentParser(description="Kitware trame")

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

        CoreServer.add_arguments(self._cli_parser)

        return self._cli_parser

    @property
    def running(self):
        return self._running_stage > 1

    # -------------------------------------------------------------------------
    # API for network handling
    # -------------------------------------------------------------------------

    def get_server_state(self):
        shared_state = utils.clean_state(self.state.initial)
        state = {
            "name": self._name,
            "state": shared_state,
        }
        return state

    # -------------------------------------------------------------------------

    def add_protocol_to_configure(self, configure_protocol_fn):
        self._protocols_to_configure.append(configure_protocol_fn)

    @property
    def protocol(self):
        return self._root_protocol

    # -------------------------------------------------------------------------

    def protocol_call(self, method, *args, **kwargs):
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
        port=None,
        thread=False,
        open_browser=True,
        show_connection_info=True,
        disableLogging=False,
        backend="aiohttp",
        exec_mode="main",
        timeout=None,
        **kwargs,
    ):
        if self._running_stage:
            return

        CoreServer.bind_server(self)
        options = self.cli.parse_known_args()[0]

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

        if show_connection_info and exec_mode != "task":
            from .utils.server import print_informations

            self.controller.on_server_ready.add(
                lambda **kwargs: print_informations(self)
            )

        if open_browser and exec_mode != "task" and not options.server:
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

        CoreServer.configure(options)

        self._running_stage = 1
        task = CoreServer.server_start(
            options,
            disableLogging=disableLogging,
            backend=backend,
            exec_mode=exec_mode,
            **kwargs,
        )

        # Manage exit life cycle unless coroutine
        if exec_mode == "main":
            self._running_stage = 0
            if self.controller.on_server_exited.exists():
                self.controller.on_server_exited(**self.state.to_dict())
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
        if self._running_stage:
            await self._server.stop()

    @property
    def port(self):
        return self._running_port

    # -------------------------------------------------------------------------
    # Extract client side of current app instance with its enabled modules
    # -------------------------------------------------------------------------

    def write_www(self, destination_directory=None):
        if destination_directory is None:
            print(
                "Need to provide a destination directory to write into "
                "the trame client."
            )
            return

        if self._www:
            shutil.copytree(self._www, destination_directory, dirs_exist_ok=True)
            for sub_path, src_dir in self.serve.items():
                dst_dir = os.path.join(destination_directory, sub_path)
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        else:
            print("Skip export as no module have been activated.")
