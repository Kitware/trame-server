import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from enum import Enum, auto
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from trame_server import Server
from trame_server.utils.typed_state import (
    DefaultEncoderDecoder,
    IStateEncoderDecoder,
    TypedState,
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
    typed_state = TypedState(state, MyData)

    assert typed_state.data.a == 1
    typed_state.data.a = 42
    assert state[typed_state.name.a] == 42


def test_can_be_constructed_from_nested_dataclass(state):
    typed_state = TypedState(state, MyBiggerData)

    assert typed_state.data.my_other_data.a == 1
    typed_state.data.my_other_data.a = 42
    assert state[typed_state.name.my_other_data.a] == 42


def test_can_handle_namespace(state):
    typed_state_ns1 = TypedState(state, MyData, namespace="ns1")
    typed_state_ns2 = TypedState(state, MyData, namespace="ns2")

    typed_state_ns1.data.a = 40
    typed_state_ns2.data.a = 3

    assert typed_state_ns2.data.a != typed_state_ns1.data.a


def test_can_be_converted_to_dataclass(state):
    typed_state = TypedState(state, MyBiggerData)
    typed_state.data.my_other_data.a = 42
    typed_state.data.my_other_data.b = 43
    typed_state.data.c = 44

    assert typed_state.get_dataclass() == MyBiggerData(
        my_other_data=MyData(a=42, b=43), c=44
    )
    assert TypedState.as_dataclass(typed_state.data.my_other_data) == MyData(a=42, b=43)


def test_can_be_set_from_data_class(state):
    typed_state = TypedState(state, MyBiggerData)

    typed_state.set_dataclass(MyBiggerData(my_other_data=MyData(a=42, b=43), c=44))
    assert typed_state.data.my_other_data.a == 42
    assert typed_state.data.my_other_data.b == 43
    assert typed_state.data.c == 44

    TypedState.from_dataclass(typed_state.data.my_other_data, MyData(a=45, b=46))
    assert typed_state.data.my_other_data.a == 45
    assert typed_state.data.my_other_data.b == 46


def test_can_be_used_to_connect_to_state_changes(state):
    typed_state = TypedState(state, MyBiggerData, namespace="ns1")

    mock = MagicMock()

    @state.change(typed_state.name.my_other_data.a)
    def on_a_change(**_):
        mock(typed_state.data.my_other_data.a)

    typed_state.data.my_other_data.a = 53
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
    my_enum_tuple: tuple[MyEnum]
    my_enum_list: list[MyEnum]
    my_enum_dict: dict[MyEnum, MyEnum]
    my_datetime: datetime
    my_date: date
    my_time: time
    my_path: Path


def test_has_default_encoders_and_decoders_for_basic_types(state):
    typed_state = TypedState(state, DataWithTypes)
    typed_state.data.my_enum = MyEnum.B
    uuid = uuid4()
    typed_state.data.my_uuid = uuid
    typed_state.data.my_enum_tuple = (MyEnum.A, MyEnum.C)
    typed_state.data.my_enum_list = [MyEnum.A, MyEnum.C]
    typed_state.data.my_enum_dict = {MyEnum.A: MyEnum.B}

    dt = datetime.now(tz=timezone.utc)
    typed_state.data.my_datetime = dt
    typed_state.data.my_date = dt.date()
    typed_state.data.my_time = dt.time()
    typed_state.data.my_path = Path(__file__)

    assert typed_state.data.my_enum == MyEnum.B
    assert typed_state.data.my_uuid == uuid
    assert typed_state.data.my_enum_tuple == (MyEnum.A, MyEnum.C)
    assert typed_state.data.my_enum_list == [MyEnum.A, MyEnum.C]
    assert typed_state.data.my_enum_dict == {MyEnum.A: MyEnum.B}
    assert typed_state.data.my_datetime == dt
    assert typed_state.data.my_date == dt.date()
    assert typed_state.data.my_time == dt.time()
    assert typed_state.data.my_path == Path(__file__)

    assert state[typed_state.name.my_enum] == MyEnum.B.value
    assert state[typed_state.name.my_uuid] == str(uuid)
    assert state[typed_state.name.my_enum_tuple] == (MyEnum.A.value, MyEnum.C.value)
    assert state[typed_state.name.my_enum_list] == [MyEnum.A.value, MyEnum.C.value]
    assert state[typed_state.name.my_enum_dict] == {MyEnum.A.value: MyEnum.B.value}
    assert state[typed_state.name.my_datetime] == dt.isoformat()
    assert state[typed_state.name.my_date] == dt.date().isoformat()
    assert state[typed_state.name.my_time] == dt.time().isoformat()
    assert state[typed_state.name.my_path] == Path(__file__).as_posix()


def test_can_customize_encoders_and_decoders(state):
    class MyEncoder(IStateEncoderDecoder):
        def decode(self, _obj, _obj_type: type):
            return 42

        def encode(self, obj):
            return str(obj)

    typed_state = TypedState(state, DataWithTypes, encoders=[MyEncoder()])
    typed_state.data.my_enum = MyEnum.B
    assert state[typed_state.name.my_enum] == str(MyEnum.B)
    assert typed_state.data.my_enum == 42


@dataclass
class MyDataWithFactory:
    a: list[MyEnum] = field(default_factory=lambda: [MyEnum.A, MyEnum.B])


def test_is_compatible_with_default_factory(state):
    typed_state = TypedState(state, MyDataWithFactory)
    assert state[typed_state.name.a] == [MyEnum.A.value, MyEnum.B.value]


def test_different_data_classes_with_same_name_are_not_mangled_by_default(state):
    @dataclass
    class A:
        a: int = 42

    @dataclass
    class B:
        a: float = 32.3

    a = TypedState(state, A)
    b = TypedState(state, B)
    a.data.a = 3
    assert b.data.a == 32.3


def test_state_field_is_consistent_for_nested_proxies(state):
    typed_state = TypedState(state, MyBiggerData)
    data_fields = TypedState.get_field_proxy_dict(typed_state.data)

    # root data fields contains : data, data.c, data.my_other_data, data.my_other_data.a, my_other_data.b
    assert len(data_fields) == 5

    # inner field contains: my_other_data, my_other_data.a, my_other_data.b
    assert len(TypedState.get_field_proxy_dict(typed_state.data.my_other_data)) == 3


def test_can_bind_state_names_to_strongly_typed_state_callback(state):
    typed_state = TypedState(state, DataWithTypes)

    mock = MagicMock()
    typed_state.bind_changes(
        {(typed_state.name.my_date, typed_state.name.my_time): mock}
    )

    dt = datetime.now(tz=timezone.utc)

    typed_state.data.my_date = dt.date()
    typed_state.data.my_time = dt.time()

    state.flush()
    mock.assert_called_once_with(dt.date(), dt.time())


def test_can_bind_state_names_to_inner_dataclass_types(state):
    typed_state = TypedState(state, MyBiggerData)

    mock = MagicMock()
    typed_state.bind_changes(
        {(typed_state.name.my_other_data, typed_state.name.c): mock}
    )
    typed_state.data.my_other_data.a = 54

    state.flush()
    mock.assert_called_once_with(typed_state.data.my_other_data, typed_state.data.c)


def test_can_bind_to_full_typed_state(state):
    typed_state = TypedState(state, MyBiggerData)

    mock = MagicMock()
    typed_state.bind_changes({typed_state.name: mock})
    typed_state.data.my_other_data.a = 54
    state.flush()

    mock.assert_called_once_with(typed_state.data)


def test_data_proxies_key_binding_is_unpacked_for_inner_states(state):
    typed_state = TypedState(state, MyBiggerData)
    state_keys = TypedState.get_reactive_state_id_keys(
        [typed_state.name.my_other_data, typed_state.name.c]
    )
    assert state_keys == [
        typed_state.name.my_other_data.a,
        typed_state.name.my_other_data.b,
        TypedState.get_state_id(typed_state.name.my_other_data),
        typed_state.name.c,
    ]


def test_data_proxies_value_key_is_inner_state_id_for_inner_states(state):
    typed_state = TypedState(state, MyBiggerData)

    value_keys = TypedState.get_value_state_keys(
        [typed_state.data, typed_state.data.my_other_data]
    )
    assert value_keys == [
        TypedState.get_state_id(typed_state.data),
        TypedState.get_state_id(typed_state.data.my_other_data),
    ]

    field_dict = TypedState.get_field_proxy_dict(typed_state.data)
    assert all(k in field_dict for k in value_keys)


def test_can_bind_to_arbitrary_callback_args(state):
    typed_state = TypedState(state, MyBiggerData)

    mock_b = MagicMock()

    def my_callback(arbitrary_a, other_b):
        mock_b(arbitrary_a, other_b)

    typed_state.bind_changes(
        {(typed_state.name.my_other_data.b, typed_state.name.c): my_callback}
    )

    typed_state.data.my_other_data.b = 2
    typed_state.data.c = 3.4
    state.flush()

    mock_b.assert_called_once_with(2, 3.4)


class CustomEnumEncode(DefaultEncoderDecoder):
    def encode(self, obj):
        if isinstance(obj, MyEnum):
            return obj.name + "_CUSTOM"
        return super().encode(obj)

    def decode(self, obj, obj_type: type):
        if issubclass(obj_type, MyEnum) and isinstance(obj, str):
            return MyEnum[obj.replace("_CUSTOM", "")]
        return super().decode(obj, obj_type)


def test_can_encode_values_consistently_with_proxy_encoding(state):
    typed_state = TypedState(
        state,
        MyBiggerData,
        encoders=[CustomEnumEncode()],
    )

    assert typed_state.encode([{"text": e.name, "value": e} for e in MyEnum]) == [
        {"text": e.name, "value": e.name + "_CUSTOM"} for e in MyEnum
    ]


def test_can_check_if_is_specific_proxy_type(state):
    typed_state = TypedState(state, MyBiggerData)
    assert TypedState.is_name_proxy_class(typed_state.name.my_other_data)
    assert TypedState.is_data_proxy_class(typed_state.data.my_other_data)


@dataclass
class DualState:
    d1: MyData = field(default_factory=MyData)
    d2: MyData = field(default_factory=MyData)


def test_supports_creating_sub_states(state):
    typed_state = TypedState(state, DualState)

    sub_state_1 = typed_state.get_sub_state(typed_state.name.d1)
    assert isinstance(sub_state_1, TypedState)
    assert sub_state_1.name.a == typed_state.name.d1.a

    typed_state.data.d1.a = 808
    assert sub_state_1.data.a == 808

    sub_state_2 = typed_state.get_sub_state(typed_state.name.d2)
    assert sub_state_2.name.a == typed_state.name.d2.a

    assert sub_state_1._encoder == sub_state_2._encoder == typed_state._encoder


@pytest.mark.asyncio
async def test_is_compatible_with_async_bind_changes(state):
    typed_state = TypedState(state, MyData)

    mock = MagicMock()

    async def async_callback(value):
        await asyncio.sleep(0.1)
        mock(value)

    typed_state.bind_changes({typed_state.name.a: async_callback})

    with state:
        typed_state.data.a = 43

    await asyncio.sleep(0.05)
    mock.assert_not_called()
    await asyncio.sleep(0.1)
    mock.assert_called_once_with(43)


@dataclass
class DataWithUnionTypes:
    my_optional_enum: MyEnum | None
    my_str_or_enum: str | MyEnum
    my_enum_or_str: MyEnum | str
    my_optional_enum_list: list[MyEnum | str | None] | None


def test_handles_union_types_by_order_of_definition(state):
    encode = CustomEnumEncode()
    typed_state = TypedState(state, DataWithUnionTypes, encoders=[encode])

    b_enum = MyEnum.B
    b_str = encode.encode(b_enum)

    typed_state.data.my_optional_enum = None
    typed_state.data.my_str_or_enum = b_str
    typed_state.data.my_enum_or_str = b_str

    assert typed_state.data.my_optional_enum is None
    assert typed_state.data.my_str_or_enum == b_str
    assert typed_state.data.my_enum_or_str == b_enum

    assert state[typed_state.name.my_optional_enum] is None
    assert state[typed_state.name.my_str_or_enum] == b_str
    assert state[typed_state.name.my_enum_or_str] == b_str

    typed_state.data.my_optional_enum = b_enum
    typed_state.data.my_str_or_enum = b_enum
    typed_state.data.my_enum_or_str = b_enum
    assert typed_state.data.my_optional_enum == b_enum
    assert typed_state.data.my_str_or_enum == b_str
    assert typed_state.data.my_enum_or_str == b_enum

    assert state[typed_state.name.my_optional_enum] == b_str
    assert state[typed_state.name.my_str_or_enum] == b_str
    assert state[typed_state.name.my_enum_or_str] == b_str


def test_handles_list_of_union(state):
    encode = CustomEnumEncode()
    typed_state = TypedState(state, DataWithUnionTypes, encoders=[encode])

    b_enum = MyEnum.B
    b_str = encode.encode(b_enum)

    typed_state.data.my_optional_enum_list = None
    assert typed_state.data.my_optional_enum_list is None

    typed_state.data.my_optional_enum_list = [b_str, b_enum, None]
    assert typed_state.data.my_optional_enum_list == [b_enum, b_enum, None]
    assert state[typed_state.name.my_optional_enum_list] == [b_str, b_str, None]


def test_failure_to_encode_raises_type_error(state):
    class RaiseEncode(DefaultEncoderDecoder):
        def encode(self, _obj):
            raise AssertionError()

        def decode(self, _obj, _obj_type: type):
            raise AssertionError()

    typed_state = TypedState(state, DataWithTypes, encoders=[RaiseEncode()])
    state.setdefault(typed_state.name.my_enum, MyEnum.A.value)

    with pytest.raises(TypeError):
        typed_state.data.my_enum = MyEnum.A

    with pytest.raises(TypeError):
        print(typed_state.data.my_enum)


@dataclass
class SimpleTypes:
    my_int: int
    my_enum: MyEnum
    my_path: Path


@dataclass
class TypedComposite:
    simple_types: SimpleTypes = field(default_factory=SimpleTypes)


@dataclass
class DataclassCollections:
    nested_list: list[TypedComposite] = field(default_factory=list)
    nested_dict: dict[str, TypedComposite] = field(default_factory=dict)


def test_encode_decode_supports_collections_of_nested_dataclass(state):
    typed_state = TypedState(state, DataclassCollections)
    typed_state.data.nested_list = [
        TypedComposite(
            SimpleTypes(my_int=1, my_enum=MyEnum.A, my_path=Path("/path/to/1"))
        ),
        TypedComposite(
            SimpleTypes(my_int=2, my_enum=MyEnum.B, my_path=Path("/path/to/2"))
        ),
    ]

    typed_state.data.nested_dict = {
        "3": TypedComposite(
            SimpleTypes(my_int=3, my_enum=MyEnum.C, my_path=Path("/path/to/3"))
        ),
        "4": TypedComposite(
            SimpleTypes(my_int=4, my_enum=MyEnum.A, my_path=Path("/path/to/4"))
        ),
    }

    assert typed_state.data.nested_list[0] == TypedComposite(
        SimpleTypes(my_int=1, my_enum=MyEnum.A, my_path=Path("/path/to/1"))
    )
    assert typed_state.data.nested_list[1] == TypedComposite(
        SimpleTypes(my_int=2, my_enum=MyEnum.B, my_path=Path("/path/to/2"))
    )
    assert typed_state.data.nested_dict["3"] == TypedComposite(
        SimpleTypes(my_int=3, my_enum=MyEnum.C, my_path=Path("/path/to/3"))
    )
    assert typed_state.data.nested_dict["4"] == TypedComposite(
        SimpleTypes(my_int=4, my_enum=MyEnum.A, my_path=Path("/path/to/4"))
    )

    assert state[typed_state.name.nested_list] == [
        {
            "simple_types": {
                "my_int": 1,
                "my_enum": typed_state.encode(MyEnum.A),
                "my_path": typed_state.encode("/path/to/1"),
            }
        },
        {
            "simple_types": {
                "my_int": 2,
                "my_enum": typed_state.encode(MyEnum.B),
                "my_path": typed_state.encode("/path/to/2"),
            }
        },
    ]

    assert state[typed_state.name.nested_dict] == {
        "3": {
            "simple_types": {
                "my_int": 3,
                "my_enum": typed_state.encode(MyEnum.C),
                "my_path": typed_state.encode("/path/to/3"),
            }
        },
        "4": {
            "simple_types": {
                "my_int": 4,
                "my_enum": typed_state.encode(MyEnum.A),
                "my_path": typed_state.encode("/path/to/4"),
            }
        },
    }
