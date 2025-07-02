from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from enum import Enum, auto
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from trame_server import Server
from trame_server.utils.typed_state import (
    CollectionEncoderDecoder,
    DefaultEncoderDecoder,
    IStateEncoderDecoder,
    TypedState,
    as_dataclass,
    bind_typed_state_change,
    from_dataclass,
    get_field_proxy_dict,
    get_reactive_state_id_keys,
    get_state_id,
    get_value_state_keys,
    state_proxies,
    state_proxy,
)


@pytest.fixture
def state():
    server = Server()
    server.state.ready()
    return server.state


@dataclass
class MyData:
    a: int = 1
    b: int = 2


@dataclass
class MyBiggerData:
    my_other_data: MyData = field(default_factory=MyData)
    c: float = 42.0


def test_can_be_constructed_from_simple_dataclass(state):
    data, data_name = state_proxies(MyData, state)

    assert data.a == 1
    data.a = 42
    assert state[data_name.a] == 42


def test_can_be_constructed_from_nested_dataclass(state):
    data, data_name = state_proxies(MyBiggerData, state)

    assert data.my_other_data.a == 1
    data.my_other_data.a = 42
    assert state[data_name.my_other_data.a] == 42


def test_can_handle_namespace(state):
    my_data_ns1 = state_proxy(MyData, state, state_namespace="ns1")
    my_data_ns2 = state_proxy(MyData, state, state_namespace="ns2")

    my_data_ns1.a = 40
    my_data_ns2.a = 3

    assert my_data_ns2.a != my_data_ns1.a


def test_can_be_converted_to_from_dataclass(state):
    data = state_proxy(MyBiggerData, state)
    data.my_other_data.a = 42
    data.my_other_data.b = 43
    data.c = 44

    assert as_dataclass(data) == MyBiggerData(my_other_data=MyData(a=42, b=43), c=44)


def test_can_be_set_from_data_class(state):
    data = state_proxy(MyBiggerData, state)

    from_dataclass(data, MyBiggerData(my_other_data=MyData(a=42, b=43), c=44))
    assert data.my_other_data.a == 42
    assert data.my_other_data.b == 43
    assert data.c == 44


def test_can_be_used_to_connect_to_state_changes(state):
    data, data_names = state_proxies(MyBiggerData, state, state_namespace="ns1")

    mock = MagicMock()

    @state.change(data_names.my_other_data.a)
    def on_a_change(**_):
        mock(data.my_other_data.a)

    data.my_other_data.a = 53
    state.flush()

    mock.assert_called_once_with(53)


class MyEnum(Enum):
    A = auto()
    B = auto()
    C = auto()


@dataclass
class DataWithTypes:
    my_enum: MyEnum
    my_uuid: UUID
    my_enum_list: list[MyEnum]
    my_enum_dict: dict[MyEnum, MyEnum]
    my_datetime: datetime
    my_date: date
    my_time: time


def test_has_default_encoders_and_decoders_for_basic_types(state):
    data, data_name = state_proxies(DataWithTypes, state)
    data.my_enum = MyEnum.B
    uuid = uuid4()
    data.my_uuid = uuid
    data.my_enum_list = [MyEnum.A, MyEnum.C]
    data.my_enum_dict = {MyEnum.A: MyEnum.B}

    dt = datetime.now(tz=timezone.utc)
    data.my_datetime = dt
    data.my_date = dt.date()
    data.my_time = dt.time()

    assert data.my_enum == MyEnum.B
    assert data.my_uuid == uuid
    assert data.my_enum_list == [MyEnum.A, MyEnum.C]
    assert data.my_enum_dict == {MyEnum.A: MyEnum.B}
    assert data.my_datetime == dt
    assert data.my_date == dt.date()
    assert data.my_time == dt.time()

    assert state[data_name.my_enum] == MyEnum.B.value
    assert state[data_name.my_uuid] == str(uuid)
    assert state[data_name.my_enum_list] == [MyEnum.A.value, MyEnum.C.value]
    assert state[data_name.my_enum_dict] == {MyEnum.A.value: MyEnum.B.value}
    assert state[data_name.my_datetime] == dt.isoformat()
    assert state[data_name.my_date] == dt.date().isoformat()
    assert state[data_name.my_time] == dt.time().isoformat()


def test_can_customize_encoders_and_decoders(state):
    class MyEncoder(IStateEncoderDecoder):
        def decode(self, _obj, _obj_type: type):
            return 42

        def encode(self, obj):
            return str(obj)

    data, data_name = state_proxies(DataWithTypes, state, state_encoder=MyEncoder())
    data.my_enum = MyEnum.B
    assert state[data_name.my_enum] == str(MyEnum.B)
    assert data.my_enum == 42


@dataclass
class MyDataWithFactory:
    a: list[MyEnum] = field(default_factory=lambda: [MyEnum.A, MyEnum.B])


def test_is_compatible_with_default_factory(state):
    data, data_name = state_proxies(MyDataWithFactory, state)
    assert state[data_name.a] == [MyEnum.A.value, MyEnum.B.value]


def test_different_data_classes_with_same_name_are_not_mangled_by_default(state):
    @dataclass
    class A:
        a: int = 42

    @dataclass
    class B:
        a: float = 32.3

    a = state_proxy(A, state)
    b = state_proxy(B, state)
    a.a = 3
    assert b.a == 32.3


def test_state_field_is_consistent_for_nested_proxies(state):
    data = state_proxy(MyBiggerData, state)
    data_fields = get_field_proxy_dict(data)

    # root data fields contains : data, data.c, data.my_other_data, data.my_other_data.a, my_other_data.b
    assert len(data_fields) == 5

    # inner field contains: my_other_data, my_other_data.a, my_other_data.b
    assert len(get_field_proxy_dict(data.my_other_data)) == 3


def test_can_bind_state_names_to_strongly_typed_state_callback(state):
    data, data_name = state_proxies(DataWithTypes, state)

    mock = MagicMock()
    bind_typed_state_change([data_name.my_date, data_name.my_time], mock, state, data)

    dt = datetime.now(tz=timezone.utc)

    data.my_date = dt.date()
    data.my_time = dt.time()

    state.flush()
    mock.assert_called_once_with(dt.date(), dt.time())


def test_can_bind_state_names_to_inner_dataclass_types(state):
    data, data_name = state_proxies(MyBiggerData, state)

    mock = MagicMock()
    bind_typed_state_change([data_name.my_other_data, data_name.c], mock, state, data)
    data.my_other_data.a = 54

    state.flush()
    mock.assert_called_once_with(data.my_other_data, data.c)


def test_can_bind_to_full_typed_state(state):
    data, data_name = state_proxies(MyBiggerData, state)

    mock = MagicMock()
    bind_typed_state_change(data_name, mock, state, data)
    data.my_other_data.a = 54
    state.flush()

    mock.assert_called_once_with(data)


def test_data_proxies_key_binding_is_unpacked_for_inner_states(state):
    data, data_name = state_proxies(MyBiggerData, state)
    state_keys = get_reactive_state_id_keys([data_name.my_other_data, data_name.c])
    assert state_keys == [
        data_name.my_other_data.a,
        data_name.my_other_data.b,
        get_state_id(data_name.my_other_data),
        data_name.c,
    ]


def test_data_proxies_value_key_is_inner_state_id_for_inner_states(state):
    data, data_name = state_proxies(MyBiggerData, state)

    value_keys = get_value_state_keys([data, data.my_other_data])
    assert value_keys == [get_state_id(data), get_state_id(data.my_other_data)]

    field_dict = get_field_proxy_dict(data)
    assert all(k in field_dict for k in value_keys)


def test_can_use_typed_state_with_data_class(state):
    typed_state = TypedState(state, MyBiggerData)

    mock_a = MagicMock()
    mock_b = MagicMock()
    mock_c = MagicMock()

    def my_callback(arbitrary_a, other_b):
        mock_b(arbitrary_a, other_b)

    typed_state.bind_change(
        {
            typed_state.name.my_other_data.a: mock_a,
            (typed_state.name.my_other_data.b, typed_state.name.c): my_callback,
            (typed_state.name.my_other_data,): mock_c,
        }
    )

    typed_state.data.my_other_data.a = 1
    typed_state.data.my_other_data.b = 2
    typed_state.data.c = 3.4
    state.flush()

    mock_a.assert_called_once_with(1)
    mock_b.assert_called_once_with(2, 3.4)
    mock_c.assert_called_once_with(typed_state.data.my_other_data)


def test_typed_change_bind_is_compatible_with_overload(state):
    typed_state = TypedState(state, MyBiggerData)

    # key / callback
    typed_state.bind_change(typed_state.name.my_other_data.a, print)

    # Key list / callback
    typed_state.bind_change([typed_state.name.my_other_data.a], print)

    # Key tuple / callback
    typed_state.bind_change((typed_state.name.my_other_data.a,), print)

    # dict
    typed_state.bind_change({typed_state.name.my_other_data.a: print})

    # dict of tuple keys
    typed_state.bind_change({(typed_state.name.my_other_data.a,): print})


def test_typed_state_can_encode_values_consistently_with_proxy_encoding(state):
    class CustomEnumEncode(DefaultEncoderDecoder):
        def encode(self, obj):
            if isinstance(obj, MyEnum):
                return obj.name + "_CUSTOM"
            return super().encode(obj)

    typed_state = TypedState(
        state,
        MyBiggerData,
        state_encoder=CollectionEncoderDecoder([CustomEnumEncode()]),
    )

    assert typed_state.encode([{"text": e.name, "value": e} for e in MyEnum]) == [
        {"text": e.name, "value": e.name + "_CUSTOM"} for e in MyEnum
    ]
