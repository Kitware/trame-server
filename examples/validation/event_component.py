from trame.app import TrameApp, TrameComponent
from trame.ui.html import DivLayout
from trame.widgets import client, html


class ButtonComp(TrameComponent):
    def __init__(self, server, name):
        super().__init__(server)
        self._name = name
        self.state[self._name] = 0
        self._build_ui()

    def add(self):
        self.state[self._name] += 1

    def _build_ui(self):
        with DivLayout(
            self.server, template_name=self._name, connect_parent=True
        ) as self.ui:
            html.Button(
                f"Add 1 to {{{{ {self._name} }}}} - {self.ctrl.trigger_name(self.add)}",
                click=self.add,
            )


class ButtonSubComp(TrameComponent):
    def __init__(self, server, name):
        super().__init__(server)
        self._name = name
        self.state[self._name] = 0

    def add(self):
        self.state[self._name] += 1

    def ui(self):
        with html.Div():
            html.Button(
                f"Add 1 to {{{{ {self._name} }}}} - {self.ctrl.trigger_name(self.add)}",
                click=self.add,
            )


class TestEvent(TrameApp):
    def __init__(self, server=None):
        super().__init__(server)
        self.comps = [ButtonComp(self.server, f"a{i}") for i in range(3)]
        self.sub_comps = [ButtonSubComp(self.server, f"b{i}") for i in range(3)]
        self._build_ui()

    def _build_ui(self):
        with DivLayout(self.server) as self.ui:
            for c in self.comps:
                client.ServerTemplate(name=c._name)

            for sc in self.sub_comps:
                sc.ui()

            html.Button("Refresh", click=self._build_ui)


def main():
    app = TestEvent()
    app.server.start()


if __name__ == "__main__":
    main()
