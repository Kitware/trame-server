"""
Usage example of the trame_server.utils.typed_state.TypedState class.
This class provides a convenient way to create two-way bindings between a trame state and a dataclass.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum, auto
from uuid import UUID, uuid4

from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import vuetify3 as vuetify

from trame_server.utils.typed_state import (
    DefaultEncoderDecoder,
    TypedState,
)

server = get_server(client_type="vue3")
state, ctrl = server.state, server.controller


class Priority(Enum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


def current_time() -> time:
    return datetime.now().time()


@dataclass
class Inner:
    """
    Dataclasses can define default values.
    The default values will be available in the state as default values.
    """

    text_value: str = ""
    priority: Priority = Priority.MEDIUM
    tags: list[str] = field(default_factory=list)
    selected_time: time = field(default_factory=current_time)


@dataclass
class TrameState:
    """
    Dataclasses can be nested and support various types, including enums and UUIDs.
    """

    inner: Inner = field(default_factory=Inner)
    last_inner_update: datetime = field(default_factory=datetime.now)
    task_id: UUID = field(default_factory=uuid4)


class CustomEncoder(DefaultEncoderDecoder):
    def encode(self, obj):
        if isinstance(obj, time):
            return obj.isoformat(timespec="minutes")
        return super().encode(obj)


# Create TypedState instance with custom encoder
typed_state = TypedState(state, TrameState, encoders=[CustomEncoder()])


# Nested names will contain the nested field names automatically.
print(f"State field path: {typed_state.name.inner.text_value}")


# Nested instances can be split into separate typed states if needed
inner_state = typed_state.get_sub_state(typed_state.name.inner)
assert isinstance(inner_state, TypedState)
assert inner_state.name.text_value == typed_state.name.inner.text_value


# State change callbacks
def on_text_change(text_value):
    print(f"Current text: {text_value}")


def on_priority_change(priority):
    print(f"Priority changed to: {priority}")


def on_task_update(text_value: str, priority: Priority, tags: list[str]):
    print(f"Task updated - Text: {text_value}, Priority: {priority}, Tags: {tags}")


def on_inner_data_change(inner_data: Inner):
    # When binding nested dataclass, the callback uses typed_state.data.inner
    assert inner_data == typed_state.data.inner

    # Nested dataclasses can be converted back to a dataclass using the as_dataclass method
    print(f"Inner data changed: {TypedState.as_dataclass(inner_data)}")

    typed_state.data.last_inner_update = datetime.now()


def on_time_change(last_modified_time: time):
    print(f"Selected time changed: {last_modified_time}")


# TypedState provides a bind_changes method to bind state changes to strongly typed callbacks
# Notice that the key binding is not limited to dataclass leaf but includes nested classes providing flexibility to
# the binding approach.
typed_state.bind_changes(
    {
        typed_state.name.inner.text_value: on_text_change,
        typed_state.name.inner.priority: on_priority_change,
        typed_state.name.inner.selected_time: on_time_change,
        (
            typed_state.name.inner.text_value,
            typed_state.name.inner.priority,
            typed_state.name.inner.tags,
        ): on_task_update,
        (typed_state.name.inner,): on_inner_data_change,
    }
)


@ctrl.add("reset_task")
def reset_task():
    # Dataclass values can be set from a dataclass instance using the TypedState.from_dataclass method
    TypedState.from_dataclass(typed_state.data.inner, Inner())
    typed_state.data.task_id = uuid4()


with SinglePageLayout(server) as layout:
    with layout.content:
        with vuetify.VContainer(
            fluid=True,
            classes="d-flex justify-center align-center",
            style="height: 100%;",
        ):
            with vuetify.VCard(style="max-width: 500px;"):
                vuetify.VCardTitle("TypedState trame example")
                with vuetify.VCardText():
                    # Task description input
                    vuetify.VTextField(
                        v_model=(typed_state.name.inner.text_value,),
                        label="Task Description",
                        outlined=True,
                    )

                    # Priority selector
                    # Typed state encoder can be used to encode data in a consistent way for reading in the callbacks.
                    # Here the VSelect PRIORITY Enum value will be encoded by the typed_state encoder.
                    vuetify.VSelect(
                        v_model=(typed_state.name.inner.priority,),
                        items=(
                            "options",
                            typed_state.encode(
                                [{"text": p.name.title(), "value": p} for p in Priority]
                            ),
                        ),
                        item_title="text",
                        item_value="value",
                        label="Priority",
                        outlined=True,
                    )

                    # Tags input
                    vuetify.VCombobox(
                        v_model=(typed_state.name.inner.tags,),
                        label="Tags",
                        multiple=True,
                        chips=True,
                        clearable=True,
                        outlined=True,
                        style="width: 100%; max-width: 100%;",
                    )

                    # Time picker
                    vuetify.VTextField(
                        v_model=(typed_state.name.inner.selected_time,),
                        label="Selected Time",
                        type="time",
                        outlined=True,
                    )

                    # Display current task ID
                    vuetify.VTextField(
                        v_model=(typed_state.name.task_id,),
                        label="Task ID",
                        readonly=True,
                        outlined=True,
                    )

                    # Display last modification date
                    vuetify.VTextField(
                        v_model=(typed_state.name.last_inner_update,),
                        label="Last Updated",
                        readonly=True,
                        outlined=True,
                    )

                with vuetify.VCardActions():
                    vuetify.VBtn(
                        "Reset Task",
                        color="primary",
                        click=ctrl.reset_task,
                    )


server.start()
