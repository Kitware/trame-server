import trame_server

from trame.app import get_server
from trame.decorators import TrameApp, trigger
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3 as v3


@TrameApp()
class MainApp:
    def __init__(self, server=None):
        self.server = get_server(server)
        self._build_ui()

        SecondApp(self.server)

    def _build_ui(self):
        with SinglePageLayout(self.server, full_height=True) as layout:
            with layout.content:
                v3.VBtn(
                    "Open Second App",
                    click="window.open('/?ui=second', target='_blank')",
                )
                v3.VBtn("Test Trigger", click="trame.trigger('test')")
                v3.VBtn("Unique Main Trigger", click="trame.trigger('main')")

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

        # timing thing to get name resoved
        self.server.trigger("second")(self.second_trigger)

        self._build_ui(template_name)

    @trigger("test")
    def test_trigger(self):
        print("test second")

    @trigger("second")
    def second_trigger(self):
        print("unique second")

    def _build_ui(self, template_name):
        print(self.server)
        with SinglePageLayout(
            self.server, template_name=template_name, full_height=True
        ) as layout:
            with layout.toolbar.clear() as toolbar:
                toolbar.density = "compact"
                toolbar.title = "Data Table Example"

            with layout.content:
                v3.VBtn("Test Trigger", click=f"trame.trigger('{self.prefix}test')")
                v3.VBtn("Test Trigger ctrl", click=self.test_trigger)
                v3.VBtn(
                    "Unique Second Trigger",
                    click=f"trame.trigger('{self.prefix}second')",
                )
                v3.VBtn("Unique Second Trigger ctrl", click=self.second_trigger)
                v3.VBtn(
                    "Unique Second Trigger fix",
                    click=f"trame.trigger('{self.server.controller.trigger_name(self.second_trigger)}')",
                )


def main():
    app = MainApp()
    app.server.start()


if __name__ == "__main__":
    main()
