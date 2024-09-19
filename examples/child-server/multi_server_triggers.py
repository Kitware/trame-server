import random

import trame_server

from trame.app import get_server
from trame.decorators import TrameApp, change, trigger
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3 as v3


def build_dialog():
    with v3.VDialog(v_model=("dialog_show", False), width=300) as d:
        v3.VCard(title="Test", text="This is a dialog.")

        # force state default at exec so translation can work
        d.html


@TrameApp()
class MainApp:
    def __init__(self, server=None):
        self.server = get_server(server)
        self._build_ui()

        SecondApp(self.server)

    def _build_ui(self):
        with SinglePageLayout(self.server, full_height=True) as layout:
            with layout.content:
                build_dialog()
                v3.VBtn(
                    "Open Second App",
                    click="window.open('/?ui=second', target='_blank')",
                )
                v3.VBtn("Test Trigger", click="trame.trigger('test')")
                v3.VBtn("Unique Main Trigger", click="trame.trigger('main')")
                v3.VBtn("Show dialog", click="dialog_show = true")

    @trigger("test")
    def test_trigger(self):
        print("test main")

    @trigger("main")
    def main_trigger(self):
        print("unique main")


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
        self.translator = self.server.translator

        self.state.random_value = random.random()

        # timing thing to get name resoved
        self.server.trigger("second")(self.second_trigger)

        self._build_ui(template_name)

    @trigger("test")
    def test_trigger(self):
        print("test second")

    @trigger("second")
    def second_trigger(self):
        print("unique second")

    @change("random_value")
    def random_value_changed(self, **_):
        print(f"Random value changed to: {self.state.random_value}")

    def _build_ui(self, template_name):
        # self.state.dialog_show = False
        with SinglePageLayout(
            self.server, template_name=template_name, full_height=True
        ) as layout:
            with layout.toolbar.clear() as toolbar:
                toolbar.density = "compact"
                toolbar.title = "Data Table Example"

            with layout.content:
                build_dialog()
                v3.VBtn("Test Trigger", click=f"trame.trigger('{self.prefix}test')")
                v3.VBtn("Test Trigger ctrl", click=self.test_trigger)
                v3.VBtn(
                    "Unique Second Trigger",
                    click=f"trame.trigger('{self.prefix}second')",
                )
                v3.VBtn("Unique Second Trigger ctrl", click=self.second_trigger)
                v3.VBtn(
                    "Unique Second Trigger fix",
                    click=f"trame.trigger('{self.ctrl.trigger_name(self.second_trigger)}')",
                )
                v3.VBtn(
                    "Show dialog",
                    click=self.translator.translate_js_expression(
                        self.state, "dialog_show = true"
                    ),
                )
                v3.VBtn(
                    "Change random_value",
                    click=self.translator.translate_js_expression(
                        self.state, "random_value = Math.random()"
                    ),
                )


def main():
    app = MainApp()
    app.server.start()


if __name__ == "__main__":
    main()
