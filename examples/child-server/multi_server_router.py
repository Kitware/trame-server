from trame.app import TrameApp
from trame.decorators import controller, trigger
from trame.ui.router import RouterViewLayout
from trame.ui.vuetify3 import SinglePageLayout, VAppLayout
from trame.widgets import router
from trame.widgets import vuetify3 as v3

import trame_server


class FirstApp(TrameApp):
    def __init__(self, server: trame_server.Server | str | None = None) -> None:
        super().__init__(server)

        self.state.test = "first"

        self._build_ui()

    @trigger("test")
    def test_trigger(self) -> None:
        print(self.state.test)

    @controller.add("test_controller")
    def test_controller(self) -> None:
        print(self.state.test)

    def _build_ui(self) -> None:
        with VAppLayout(self.server, full_height=True), v3.VContainer(), v3.VCard(
            title="This is the first app"
        ):
            v3.VBtn("Test Trigger", click="console.log(test); trame.trigger('test');")
            v3.VBtn("Test Controller", click=self.ctrl.test_controller)


class SecondApp(TrameApp):
    def __init__(self, server: trame_server.Server | str | None = None) -> None:
        super().__init__(server)

        self.state.test = "second"

        self._build_ui()

    @trigger("test")
    def trigger_test(self) -> None:
        print(self.state.test)

    @controller.add("test_controller")
    def test_controller(self) -> None:
        print(self.state.test)

    def _build_ui(self) -> None:
        with VAppLayout(self.server, full_height=True), v3.VContainer(), v3.VCard(
            title="This is the second app"
        ):
            v3.VBtn("Test Trigger", click="console.log(test); trame.trigger('test');")
            v3.VBtn("Test Controller", click=self.ctrl.test_controller)


class MainApp(TrameApp):
    def __init__(self, server: trame_server.Server | str | None = None):
        super().__init__(server)

        self.state.test = "main"

        self._build_ui()

    @trigger("test")
    def test_trigger(self) -> None:
        print(self.state.test)

    def _build_ui(self) -> None:
        # Register routes
        with RouterViewLayout(self.server, "/"):
            FirstApp(self.server.create_child_server(prefix="first_route_"))
        with RouterViewLayout(self.server, "/second"):
            SecondApp(self.server.create_child_server(prefix="second_route_"))

        with SinglePageLayout(self.server, full_height=True) as layout:
            with layout.toolbar:
                with v3.VStepper(
                    alt_labels=True,
                    editable=True,
                ):
                    v3.VStepperItem(
                        title="First app",
                        value="1",
                        click="$router.push('/')",
                    )
                    v3.VStepperItem(
                        title="Second app",
                        value="2",
                        click="$router.push('/second')",
                    )
                v3.VSpacer()
                v3.VBtn("Test", click="console.log(test); trame.trigger('test')")

            with layout.content:
                router.RouterView()


def main() -> None:
    app = MainApp()
    app.server.start()


if __name__ == "__main__":
    main()
