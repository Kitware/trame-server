# import json
# import logging
from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html

# logging.basicConfig(level=logging.INFO)

CLIENT_TYPE = "vue3"


class BasicApp:
    def __init__(self, server=None, template_name="main"):
        self.server = get_server(server, client_type=CLIENT_TYPE)
        self.ui = self._build_ui(template_name)
        self.state.a = 1
        self.state["b"] = 2
        self.state.update(
            {
                "c": 3,
                "d": 4,
            }
        )
        self.state.setdefault("e", 5)

        self.ctrl.plus = self.add
        self.ctrl.minus = self.remove

    def add(self):
        self.state.f += 1

    def remove(self):
        self.state.f += 1

    def _build_ui(self, name):
        with DivLayout(self.server, template_name=name) as layout:
            html.Input(type="range", v_model_number=("f", 10), min=-10, max=10, step=1)
            html.Div("Bigger than 5", v_show="Math.abs(f)>5")
            html.Div(
                "Current value {{ Math.abs(f) + f }} <=> {{ f }}",
            )

            return layout

    @property
    def state(self):
        return self.server.state

    @property
    def ctrl(self):
        return self.server.controller


def main():
    root_server = get_server(client_type=CLIENT_TYPE)
    one_of_the_app = None
    for app_name in ["main", "a", "b", "c"]:
        child_server = root_server.create_child_server(prefix=f"{app_name}_")
        app = BasicApp(child_server, app_name)
        app.add()
        app.ctrl.plus()
        one_of_the_app = app

    # root_server.controller.on_server_ready.add(lambda **kwargs: print(json.dumps(root_server.state.to_dict(), indent=2)))
    root_server.controller.on_server_ready.add(
        lambda **kwargs: print("Root server ready")
    )
    one_of_the_app.server.controller.on_server_ready.add(
        lambda **kwargs: print("Sub server ready")
    )
    one_of_the_app.server.start()


if __name__ == "__main__":
    main()
