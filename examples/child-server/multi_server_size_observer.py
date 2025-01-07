from trame.app import get_server
from trame.decorators import TrameApp, change
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import client
from trame.widgets import vuetify3 as v3

import trame_server


@TrameApp()
class MainApp:
    def __init__(self, server=None):
        self.server = get_server(server)
        self._build_ui()

        SecondApp(self.server)

    def _build_ui(self):
        with SinglePageLayout(self.server, full_height=True) as layout:
            with layout.content:
                with client.SizeObserver("main_size_observer"):
                    with v3.VContainer():
                        v3.VBtn(
                            "Open Second App",
                            click="window.open('/?ui=second', target='_blank')",
                        )

    @change("main_size_observer")
    def main_size_observer(self, main_size_observer, **_):
        print("main_size_observer", main_size_observer)


@TrameApp()
class SecondApp:
    def __init__(
        self, server: trame_server.Server | None = None, template_name="second"
    ):
        self.prefix = ""
        if server:
            self.prefix = "second_"
            self.server = server.create_child_server(prefix=self.prefix)
        else:
            self.server = get_server(server)

        self.state = self.server.state
        self.ctrl = self.server.controller

        self._build_ui(template_name)
        # server.state.change("second_size_observer")(lambda **_: print("second size"))

    @change("second_size_observer")
    def second_size_observer(self, **_):
        print("second_size_observer", self.state.second_size_observer)

    def _build_ui(self, template_name):
        # self.state.dialog_show = False
        with SinglePageLayout(
            self.server, template_name=template_name, full_height=True
        ) as layout:
            with layout.content:
                with client.SizeObserver("second_size_observer"):
                    with v3.VContainer():
                        v3.VBtn("Hello")


def main():
    app = MainApp()
    app.server.start()


if __name__ == "__main__":
    main()
