import asyncio
from multiprocessing import Process, Queue
from .asynchronous import handle_task_result


class BrowserProcess(Process):
    def __init__(
        self, title=None, port=None, msg_queue=None, debug=False, gui=None, **kwargs
    ):
        Process.__init__(self)
        self._title = title
        self._port = port
        self._msg_queue = msg_queue
        self._window_args = kwargs
        self._main_window = None
        # start args
        self._debug = debug
        self._gui = gui

    def exit(self):
        # It does not appear that we need to destroy the window
        self._msg_queue.put("closing")

    def run(self):
        try:
            import webview
        except ImportError:
            print("layout.start_desktop_window() requires pywebview>=3.4")
            return

        self._main_window = webview.create_window(
            title=self._title,
            url=f"http://localhost:{self._port}/index.html",
            **self._window_args,
        )
        if hasattr(self._main_window, "events"):
            # Newer versions of pywebview (>=3.6) use window.events.closing
            self._main_window.events.closing += self.exit
        else:
            # Older versions (around pywebview<=3.5) use window.closing
            self._main_window.closing += self.exit

        webview.start(debug=self._debug, gui=self._gui)


def start_browser(server, **kwargs):
    _msg_queue = Queue()
    _on_msg = kwargs.get("on_message")

    async def process_msg():
        keep_processing = True
        while keep_processing:
            await asyncio.sleep(0.5)
            if not _msg_queue.empty():
                msg = _msg_queue.get_nowait()
                if _on_msg:
                    _on_msg(msg)
                if msg == "closing":
                    keep_processing = False
                    await server.stop()

    task = asyncio.create_task(process_msg())
    task.add_done_callback(handle_task_result)

    client_process = BrowserProcess(
        title=server.state.trame__title,
        port=server.port,
        msg_queue=_msg_queue,
        debug=server.options.get("desktop_debug"),
        **kwargs,
    )
    client_process.start()
