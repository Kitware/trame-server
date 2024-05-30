from pathlib import Path
from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html

server = get_server()
state = server.state

server.enable_module(
    {
        "serve": {
            "__test": str(Path(__file__).parent.resolve()),
        },
        "scripts": ["__test/stateUpdateListener.js"],
    }
)

state.msg = "Something"
state.change_count = 0


def update_state():
    server.clear_state_client_cache("msg")
    state.dirty("msg")


with DivLayout(server):
    html.Button("A", click="msg = 'something A'")
    html.Button("B", click="msg = 'something B'")
    html.Button("Force", click=update_state)
    html.Div("MSG={{ msg }} - Change count={{ change_count }}")

server.start()
