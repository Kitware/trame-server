from trame.app import get_server, asynchronous
from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vuetify

from trame_server.client import Client


server = get_server()
state, ctrl = server.state, server.controller
server.cli.add_argument("--url")

client = Client()

state.trame_title = "Client"
state.counter = 0


@state.change("counter")
def on_change(counter, **kwargs):
    if counter == client.state.counter:
        return

    msg = f"client::counter = {counter}"
    if state.log is None:
        state.log = ""
    state.log += msg + "\n"
    print(msg)
    # Push local state to remote server
    with client.state:
        client.state.counter = counter


async def trigger(*args, **kwargs):
    msg = f"client::trigger = {args} {kwargs}"
    if state.log is None:
        state.log = ""
    state.log += msg + "\n"
    print(msg)
    resp = await client.call_trigger("my_method", args, kwargs)
    print("Server replied with:", resp)


@client.state.change("counter")
def on_remote_change(counter, **kwargs):
    if counter == state.counter:
        return

    with state:
        msg = f"remote::counter = {counter}"
        if state.log is None:
            state.log = ""
        state.log += msg + "\n"
        print(msg)

        # Sync local state
        state.counter = counter


@client.state.change("test_file")
def on_file(test_file, **kwargs):
    with state:
        msg = f"remote::test_file = {test_file.get('name')}"
        print(list(test_file.keys()))
        state.log += msg + "\n"
        print(msg)


@client.state.change("attch_data")
def on_attachment(attch_data, **kwargs):
    with state:
        msg = f"remote::attch_data {attch_data.get('time')}"
        print(msg)
        state.log += msg + "\n"


@ctrl.add("on_server_ready")
def connect_to_server(**kwargs):
    url = server.cli.parse_args().url
    print(f"Client connect to {url}")
    asynchronous.create_task(client.connect(url, secret="wslink-secret"))


with SinglePageLayout(server) as layout:
    layout.title.set_text(state.trame_title)

    with layout.toolbar as toolbar:
        vuetify.VSpacer()
        toolbar.add_child("{{ counter }}")
        vuetify.VSpacer()
        vuetify.VBtn("-", click="counter--")
        vuetify.VBtn("+", click="counter++")
        vuetify.VBtn(
            "fn", click=(trigger, "[counter, 2]", "{a: 2 * counter, b: 3 * counter}")
        )

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
