import asyncio
import logging
import sys
import traceback

from trame.app import TrameApp
from trame.decorators import change, life_cycle
from trame.ui.html import DivLayout
from trame.widgets import html

# Disable default stdout exception
logging.getLogger("wslink.protocol").setLevel(logging.CRITICAL)


class MonitorException(TrameApp):
    def __init__(self, server=None):
        super().__init__(server)
        self.server.state.test = 1
        self.server.state.test_async = 1
        self.server.state.allow_exception = False
        self._build_ui()

    def _build_ui(self):
        with DivLayout(self.server) as self.ui:
            html.Button("Divide by 0", click=self.divide_by_zero)
            html.Button("JS error", click="console.error('Yo')")
            html.Button("Divide by 0 in change listener", click="test += 1")
            html.Button("Divide by 0 in async change listener", click="test_async += 1")

    def divide_by_zero(self):
        return 1 / 0

    @life_cycle.server_ready
    def on_ready(self, **_):
        self.state.allow_exception = True

    @life_cycle.exception
    def on_exception(self, exception):
        print(">" * 60)
        print("exception ->", exception)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stdout
        )
        print("<" * 60)

    @life_cycle.error
    def on_js_error(self, msg):
        if msg == "[object Object]":
            # exception... => should fix JS to send a better msg/event
            return

        print("JS error:", msg)

    @change("test")
    def test_is_changed(self, allow_exception, **_):
        if not allow_exception:
            return 0
        return 1 / 0

    @change("test_async")
    async def test_async_is_changed(self, allow_exception, **_):
        if not allow_exception:
            return 0
        await asyncio.sleep(0.1)
        return 1 / 0


def main():
    app = MonitorException()
    app.server.start()


if __name__ == "__main__":
    main()
