import logging

from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html

logger = logging.getLogger(__name__)
CLIENT_TYPE = "vue3"


class BasicApp:
    def __init__(self, server=None):
        self.server = get_server(server, client_type=CLIENT_TYPE)
        self.ui = self._build_ui()
        self.state.a = 1
        self.state["b"] = 2
        self.state.update(
            {
                "c": 3,
                "d": 4,
                "longer_name": "hello",
            }
        )
        self.state.setdefault("e", 5)

        self.ctrl.plus = self.add
        self.ctrl.minus = self.remove

    def add(self):
        self.state.f += 1

    def remove(self):
        self.state.f -= 1

    def _build_ui(self):
        with DivLayout(self.server) as layout:
            html.Input(type="range", v_model_number=("f", 10), min=-10, max=10, step=1)
            html.Div(
                "Bigger than 5 {{ longer_name }}",
                v_show="Math.abs(f)>5 && longer_name.length",
            )
            html.Div(
                "Current value {{ Math.abs(f) + f }} <=> {{ f }} | {{ longer_name }}",
            )

            return layout

    @property
    def state(self):
        return self.server.state

    @property
    def ctrl(self):
        return self.server.controller


def test_prefix():
    root_server = get_server("test_prefix", client_type=CLIENT_TYPE)
    main_app = BasicApp(root_server)
    child_a_app = BasicApp(root_server.create_child_server(prefix="child_a_"))
    child_b_app = BasicApp(root_server.create_child_server(prefix="child_b_"))

    main_app.state.ready()
    child_a_app.state.ready()
    child_b_app.state.ready()

    global_state = {
        k: v for k, v in main_app.state.to_dict().items() if not k.startswith("trame_")
    }
    expected = dict(
        a=1,
        b=2,
        c=3,
        d=4,
        e=5,
        f=10,
        longer_name="hello",
        child_a_a=1,
        child_a_b=2,
        child_a_c=3,
        child_a_d=4,
        child_a_e=5,
        child_a_f=10,
        child_a_longer_name="hello",
        child_b_a=1,
        child_b_b=2,
        child_b_c=3,
        child_b_d=4,
        child_b_e=5,
        child_b_f=10,
        child_b_longer_name="hello",
    )
    assert expected == global_state

    main_app.add()
    assert main_app.state.f == 11
    main_app.ctrl.plus()
    assert main_app.state.f == 12

    # with child_a_app.state:
    child_a_app.remove()
    assert child_a_app.state.f == 9
    child_a_app.remove()
    assert child_a_app.state.f == 8
    assert main_app.state.child_a_f == 8

    # with child_b_app.state:
    child_b_app.ctrl.minus()
    assert child_b_app.state.f == 9
    child_b_app.remove()
    assert child_b_app.state.f == 8
    assert main_app.state.child_b_f == 8

    # Test main app output

    expected_main = """<div >
<input v-model.number="f" max="10" min="-10" step="1" type="range" />
<div v-show="Math.abs(f)>5 && longer_name.length">
Bigger than 5 {{ longer_name }}
</div>
<div >
Current value {{ Math.abs(f) + f }} <=> {{ f }} | {{ longer_name }}
</div>
</div>"""
    # print(main_app.ui.html)
    assert main_app.ui.html == expected_main

    # Test child_a app output
    expected_child_a = """<div >
<input v-model.number="child_a_f" max="10" min="-10" step="1" type="range" />
<div v-show="Math.abs(child_a_f)>5 && child_a_longer_name.length">
Bigger than 5 {{ child_a_longer_name }}
</div>
<div >
Current value {{ Math.abs(child_a_f) + child_a_f }} <=> {{ child_a_f }} | {{ child_a_longer_name }}
</div>
</div>"""
    # print(child_a_app.ui.html)
    assert child_a_app.ui.html == expected_child_a

    # Test child_b app output
    expected_child_b = """<div >
<input v-model.number="child_b_f" max="10" min="-10" step="1" type="range" />
<div v-show="Math.abs(child_b_f)>5 && child_b_longer_name.length">
Bigger than 5 {{ child_b_longer_name }}
</div>
<div >
Current value {{ Math.abs(child_b_f) + child_b_f }} <=> {{ child_b_f }} | {{ child_b_longer_name }}
</div>
</div>"""
    # print(child_b_app.ui.html)
    assert child_b_app.ui.html == expected_child_b
