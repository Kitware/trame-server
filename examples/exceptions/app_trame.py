import logging
import sys
import traceback

from trame.app import TrameApp
from trame.decorators import life_cycle
from trame.ui.html import DivLayout
from trame.widgets import html

# Disable default stdout exception
logging.getLogger("wslink.protocol").setLevel(logging.CRITICAL)


class MonitorException(TrameApp):
    def __init__(self, server=None):
        super().__init__(server)
        self._build_ui()
        self.ctrl.on_exception.add(self.on_exception)

    def _build_ui(self):
        with DivLayout(self.server) as self.ui:
            html.Button("Divide by 0", click=self.divide_by_zero)
            html.Button("JS error", click="console.error('Yo')")

    def divide_by_zero(self):
        return 1 / 0

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


def main():
    app = MonitorException()
    app.server.start()


if __name__ == "__main__":
    main()
