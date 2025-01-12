from trame.app import get_server
from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vuetify2 as vuetify

server = get_server(client_type="vue2")
state, ctrl = server.state, server.controller

state.field1 = 1
state.field2 = 2
state.field3 = 3

VAR_NAMES = ["field1", "field2", "field3"]


@state.change(*VAR_NAMES)
def change_detected(**_):
    print(f"Triggered because {list(state.modified_keys)} changed")
    for n in state.modified_keys:
        print(f"{n} = {state[n]}")


with SinglePageLayout(server) as layout:
    with layout.content:
        with vuetify.VContainer(
            fluid=True,
            classes="d-flex justify-center align-center",
            style="height: 100%;",
        ):
            with vuetify.VCard(style="max-width: 400px;"):
                vuetify.VCardTitle("VCard")
                with vuetify.VCardText():
                    vuetify.VTextField(
                        v_model=("field1",),
                        label="Field 1",
                        outlined=True,
                    )
                    vuetify.VTextField(
                        v_model=("field2",),
                        label="Field 2",
                        outlined=True,
                    )
                    vuetify.VTextField(
                        v_model=("field3",),
                        label="Field 3",
                        outlined=True,
                    )

server.start()
