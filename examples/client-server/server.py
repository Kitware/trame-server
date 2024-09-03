import time
from pathlib import Path
from trame.app import get_server
from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vuetify

server = get_server(client_type="vue2")
state, ctrl = server.state, server.controller

state.trame_title = "Server"
state.counter = 0
state.attch_data = None


@state.change("test_file")
def on_file(test_file, **kwargs):
    if test_file is not None:
        print("Got file...", test_file.get("name"))
    else:
        print("No file...")


@state.change("counter")
def on_change(counter, **kwargs):
    msg = f"server::counter = {counter}"
    if state.log is None:
        state.log = ""
    state.log += msg + "\n"
    print(msg)


@ctrl.trigger("my_method")
def on_method(*args, **kwargs):
    msg = f"server::method {args} {kwargs}"
    if state.log is None:
        state.log = ""
    state.log += msg + "\n"
    print(msg)
    return f"It is {time.time()}s"


def test_attachment():
    content = Path(__file__)
    state.attch_data = dict(
        id=state.counter,
        time=time.time(),
        big=server.protocol.addAttachment(content.read_bytes()),
    )


with SinglePageLayout(server) as layout:
    layout.title.set_text(state.trame_title)

    with layout.toolbar as toolbar:
        vuetify.VSpacer()
        toolbar.add_child("{{ counter }}")
        vuetify.VSpacer()
        vuetify.VBtn("Test attachment", click=test_attachment)
        vuetify.VFileInput(
            v_model=("test_file", None),
            dense=True,
            hide_details=True,
            style="max-width: 300px;",
            classes="mx-2",
        )
        vuetify.VBtn("-", click="counter--")
        vuetify.VBtn("+", click="counter++")
        vuetify.VBtn("fn", click="trigger('my_method', [counter, 2], {a: 1, b: 2})")

    with layout.content:
        with vuetify.VContainer(fluid=True):
            vuetify.VTextarea(
                v_model=("log", ""),
                outlined=True,
                clearable=True,
                auto_grow=True,
            )

if __name__ == "__main__":
    server.start()
