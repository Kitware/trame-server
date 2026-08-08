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

    def _build_ui(self):
        with DivLayout(self.server) as self.ui:
            html.Button("Divide by 0", click=self.divide_by_zero)
            html.Button(
                "No method",
                click="trame.client.getConnection().getSession().call('no_rpc_endpoint', [], {})",
            )

    @life_cycle.server_ready
    def _setup_wslink_listener(self, **_):
        self.server.protocol.log_emitter.add_event_listener(
            "exception", self.on_exception
        )
        self.server.protocol.log_emitter.add_event_listener("error", self.on_error)

    def divide_by_zero(self):
        return 1 / 0

    def on_exception(self, exception):
        print(">" * 60)
        print("exception ->", exception)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stdout
        )
        print("<" * 60)

    def on_error(self, msg):
        print(">" * 60)
        print("error ->", msg)
        print("<" * 60)


def main():
    app = MonitorException()
    app.server.start()


if __name__ == "__main__":
    main()
