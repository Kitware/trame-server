from __future__ import annotations  # triggers lazy evaluation of field.type

from dataclasses import dataclass
from enum import Enum, auto

import pytest

from trame_server import Server
from trame_server.utils.typed_state import TypedState


class AnEnum(Enum):
    A = auto()
    B = auto()


@dataclass
class DataWithTypesAnnotations:
    my_enum: AnEnum


@pytest.fixture
def state():
    server = Server()
    server.state.ready()
    return server.state


def test_is_compatible_with_from_future_annotations(state):
    typed_state = TypedState(state, DataWithTypesAnnotations)
    typed_state.data.my_enum = AnEnum.B
    assert typed_state.data.my_enum == AnEnum.B
    assert state[typed_state.name.my_enum] == AnEnum.B.value
