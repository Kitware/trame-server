from abc import ABC, abstractmethod
from dataclasses import MISSING, Field, fields, is_dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from functools import singledispatchmethod
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Type,
    TypeVar,
    cast,
    get_args,
)
from uuid import UUID

from trame_server.state import State

T = TypeVar("T")


class IStateEncoderDecoder(ABC):
    """
    State to/from primitive type encoding/decoding interface.
    """

    @abstractmethod
    def encode(self, obj):
        pass

    @abstractmethod
    def decode(self, obj, obj_type: type):
        pass

    @staticmethod
    def raise_unhandled_type(obj):
        _error_msg = (
            f"Object of type {type(obj).__name__} is not trame state serializable"
        )
        raise TypeError(_error_msg)


class DefaultEncoderDecoder(IStateEncoderDecoder):
    """
    Default primitive type encoding/decoding.
    """

    def encode(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.astimezone(timezone.utc).isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.isoformat()
        return obj

    def decode(self, obj, obj_type: type):
        if issubclass(obj_type, datetime):
            return obj_type.fromisoformat(obj)
        if issubclass(obj_type, date):
            return obj_type.fromisoformat(obj)
        if issubclass(obj_type, time):
            return obj_type.fromisoformat(obj)
        # UUID, Decimal, Enum conversion use obj_type(obj) decoding
        return obj_type(obj)


class CollectionEncoderDecoder(IStateEncoderDecoder):
    """
    Encoding/decoding for lists and dicts. Delegates to an encoder list for contained types.
    Expects the encoder in its encoder list to raise TypeError when encoding / decoding a specific type is not possible.
    Encoder will continue to the following encoder if the previous one wasn't able to encode / decode it.

    :param encoders: List of encoders to use when encoding/decoding lists and dicts.
    """

    def __init__(self, encoders: list[IStateEncoderDecoder]):
        self._encoders = encoders

    def encode(self, obj):
        if isinstance(obj, dict):
            return {self.encode(key): self.encode(value) for key, value in obj.items()}

        if isinstance(obj, list):
            return [self.encode(value) for value in obj]

        for encoder in self._encoders:
            try:
                return encoder.encode(obj)
            except TypeError:
                continue
        return obj

    def decode(self, obj, obj_type: type):
        if isinstance(obj, dict):
            key_type, value_type = get_args(obj_type)
            return {
                self.decode(key, key_type): self.decode(value, value_type)
                for key, value in obj.items()
            }

        if isinstance(obj, list):
            value_type = get_args(obj_type)[0]
            return [self.decode(value, value_type) for value in obj]

        for encoder in self._encoders:
            try:
                return encoder.decode(obj, obj_type)
            except TypeError:
                continue
        return obj


class ProxyField:
    """
    Descriptor for proxy state fields to an equivalent dataclass field.
    If the dataclass provides default or default factories, will initialize the associated state to the given encoded
    state value.

    :param state: Trame State which will be mutated / read from.
    :param state_id: Associated trame string id where the data will be pushed / read from.
    :param name: Name of the source field.
    :param field_type: Type of the source field.
    :param default: Default value of the source field.
    :param default_factory: Default factory of the source field.
    :param state_encoder: Encoder/decoder class for the proxy.
    """

    def __init__(
        self,
        *,
        state: State,
        state_id: str,
        name: str,
        field_type: type,
        default,
        default_factory,
        state_encoder: IStateEncoderDecoder,
    ):
        self._state = state
        self._state_id = state_id
        self._name = name
        self._default = default
        self._encoder = state_encoder
        self._type = field_type

        # Set the default value to trame state if needed
        default_value = default
        if default_value == MISSING and default_factory != MISSING:
            default_value = default_factory()
        if default_value != MISSING:
            self._state.setdefault(self._state_id, self._encoder.encode(default_value))

    def __get__(self, instance, owner):
        return self.get_value()

    def __set__(self, instance, value):
        self.set_value(value)

    def get_value(self):
        value = self._state[self._state_id]
        return self._encoder.decode(value, self._type)

    def set_value(self, value):
        self._state[self._state_id] = self._encoder.encode(value)


class NameField:
    """
    Descriptor for fields to state id string equivalent.

    :param state_id: Associated trame string id where the data will be pushed / read from.
    """

    def __init__(self, state_id: str):
        self._state_id = state_id

    def __get__(self, instance, owner):
        return self._state_id


_STATE_PROXY_DATACLASS_TYPE = "__state_proxy_dataclass_type"
_STATE_PROXY_FIELD_DICT = "__state_proxy_field_dict"
_STATE_PROXY_STATE_ID = "__state_proxy_state_id"


def default_encoder() -> IStateEncoderDecoder:
    return CollectionEncoderDecoder([DefaultEncoderDecoder()])


def state_proxy(
    dataclass_type: Type[T],
    state: State,
    *,
    state_namespace="",
    state_encoder: IStateEncoderDecoder | None = None,
) -> T:
    """
    Returns a State proxy with the same field structure as the input dataclass and for each field returning a proxy to
    the associated state value.

    :param dataclass_type: Type of dataclass for which the proxy will be created.
    :param state: Trame state which will be mutated/read from by the proxy.
    :param state_namespace: Optional namespace for the trame state. All proxy field access will be using this namespace
        prefix.
    :param state_encoder: Optional encoder/decoder from dataclass field to trame state field. If not encoder is
        provided, will use a default encoder/decoder.
    """
    state_encoder = state_encoder or default_encoder()

    def handler(state_id: str, field: Field):
        return ProxyField(
            state=state,
            state_id=state_id,
            name=field.name,
            default=field.default,
            default_factory=field.default_factory,
            field_type=field.type,
            state_encoder=state_encoder,
        )

    return _build_proxy_cls(dataclass_type, state_namespace, handler, "__Proxy")


def state_names_proxy(dataclass_type: Type[T], *, state_namespace="") -> T:
    """
    Returns a State proxy with the same field structure as the input dataclass and for each field returning the fully
    qualified state id name associated with a dataclass leaf.

    :param dataclass_type: Type of dataclass for which the proxy will be created.
    :param state_namespace: Optional namespace for the trame state. All proxy field access will be using this namespace
        prefix.
    """

    def handler(state_id: str, _field: Field):
        return NameField(state_id=state_id)

    return _build_proxy_cls(dataclass_type, state_namespace, handler, "__ProxyName")


def state_proxies(
    dataclass_type: Type[T],
    state: State,
    *,
    state_namespace="",
    state_encoder: IStateEncoderDecoder | None = None,
) -> tuple[T, T]:
    """
    Helper function to create both state proxy and state proxy names from an input dataclass type.

    :param dataclass_type: Type of dataclass for which the proxies will be created.
    :param state: Trame state which will be mutated/read from by the proxies.
    :param state_namespace: Optional namespace for the trame state. All proxies field access will be using this
        namespace prefix.
    :param state_encoder: Optional encoder/decoder from dataclass field to trame state field. If not encoder is
        provided, will use a default encoder/decoder.
    """
    return state_proxy(
        dataclass_type=dataclass_type,
        state=state,
        state_namespace=state_namespace,
        state_encoder=state_encoder,
    ), state_names_proxy(
        dataclass_type=dataclass_type,
        state_namespace=state_namespace,
    )


def _build_proxy_cls(
    dataclass_type: Type[T],
    prefix: str,
    handler: Callable[[str, Field], Any],
    cls_suffix: str,
    proxy_field_dict: dict | None = None,
) -> T:
    namespace = {}
    class_name = dataclass_type.__name__
    inner_field_dict = {}
    prefix = f"{prefix}__{class_name}" if prefix else class_name
    for f in fields(dataclass_type):
        state_id = f"{prefix}__{f.name}"
        if is_dataclass(f.type):
            field = _build_proxy_cls(
                f.type, state_id, handler, cls_suffix, inner_field_dict
            )
        else:
            field = handler(state_id, f)

        inner_field_dict[get_state_id(field, state_id)] = field
        namespace[f.name] = field

    if proxy_field_dict is not None:
        proxy_field_dict.update(**inner_field_dict)

    # Add dataclass type, fields and state id to the proxy class
    namespace[_STATE_PROXY_DATACLASS_TYPE] = dataclass_type
    namespace[_STATE_PROXY_FIELD_DICT] = inner_field_dict
    namespace[_STATE_PROXY_STATE_ID] = prefix
    proxy_cls = type(f"{class_name}{cls_suffix}", (), namespace)

    # Create the proxy instance and add instance to the accessible proxy fields
    proxy_instance = proxy_cls()
    inner_field_dict[prefix] = proxy_instance
    return cast(T, proxy_instance)


def _get_proxy_dataclass_type(instance: T) -> Type[T] | None:
    return getattr(instance, _STATE_PROXY_DATACLASS_TYPE, None)


def _get_proxy_dataclass_type_or_raise(instance: T) -> Type[T]:
    cls = _get_proxy_dataclass_type(instance)
    if cls is None:
        _error_msg = (
            f"Expected an instance of type __Proxy got {type(instance).__name__}."
        )
        raise RuntimeError(_error_msg)
    return cls


def is_proxy_class(instance: T) -> bool:
    return _get_proxy_dataclass_type(instance) is not None


def get_state_id(instance: T, default: str = "") -> str:
    return getattr(instance, _STATE_PROXY_STATE_ID, default)


def as_dataclass(instance: T) -> T:
    """
    Converts the input state proxy instance to dataclass.
    """
    dataclass_type = _get_proxy_dataclass_type_or_raise(instance)

    kwargs = {}
    for f in fields(dataclass_type):
        attr = getattr(instance, f.name)
        if is_proxy_class(attr):
            kwargs[f.name] = as_dataclass(attr)
        else:
            kwargs[f.name] = attr

    return dataclass_type(**kwargs)


def from_dataclass(instance: T, dataclass_obj: T) -> None:
    """
    Populate the state proxy instance from the values of the given dataclass object.
    """
    dataclass_type = _get_proxy_dataclass_type_or_raise(instance)

    if not isinstance(dataclass_obj, dataclass_type):
        _error_msg = f"Expected instance of {dataclass_type.__name__}, got {type(dataclass_obj).__name__}"
        raise TypeError(_error_msg)

    for f in fields(dataclass_type):
        attr = getattr(instance, f.name)
        value = getattr(dataclass_obj, f.name)

        if is_proxy_class(attr):
            from_dataclass(attr, value)
        else:
            setattr(instance, f.name, value)


def get_field_proxy_dict(instance: T) -> dict[str, ProxyField]:
    """
    :returns: State ID to ProxyField as saved in the input instance.
    """
    _get_proxy_dataclass_type_or_raise(instance)
    return getattr(instance, _STATE_PROXY_FIELD_DICT, {})


def get_reactive_state_id_keys(keys: Iterable[Any]) -> list[str]:
    """
    returns the list of state ids to react to on change from the input.

    :param keys: tuple of either str or dataclass proxy.
    :return: list of keys
    """
    react_keys = []
    for key in keys:
        if is_proxy_class(key):
            react_keys.extend(list(get_field_proxy_dict(key).keys()))
        else:
            react_keys.append(key)
    return react_keys


def get_value_state_keys(keys: Iterable[Any]) -> list[str]:
    """
    returns the list of keys in the proxy to return when the state modified a given key.

    :param keys: tuple of either str or dataclass proxy.
    :return: list of keys present in the proxy instance field dict
    """

    return [get_state_id(key, key) for key in keys]


def bind_typed_state_change(
    keys: Any | list[Any] | tuple[Any], callback: Callable, state: State, data: T
) -> None:
    """
    Bind state id changes to callbacks.
    Callbacks are called with converted state values found with input keys.
    """
    state_id_to_field_dict = get_field_proxy_dict(data)

    if isinstance(keys, list):
        keys = tuple(keys)

    if not isinstance(keys, tuple):
        keys = (keys,)

    value_keys = get_value_state_keys(keys)

    @state.change(*get_reactive_state_id_keys(keys))
    def _on_state_change(**_):
        values = [state_id_to_field_dict[k] for k in value_keys]
        values = [v if is_proxy_class(v) else v.get_value() for v in values]
        callback(*values)


class TypedState(Generic[T]):
    """
    Helper to have access to, mutate, and be notified of state changes using a strongly typed dataclass interface.

    TypedState provides a type-safe wrapper around the trame State object, allowing to:
    - Access and modify state using dataclass field names with full type hints
    - Bind change callbacks to specific fields or combinations of fields
    - Automatically handle encoding/decoding of complex types (enums, UUIDs, dates, etc.)
    - Use namespaces to avoid conflicts between different state objects
    """

    def __init__(
        self,
        state: State,
        dataclass_type: Type[T],
        *,
        state_namespace="",
        state_encoder: IStateEncoderDecoder | None = None,
    ):
        self._encoder = state_encoder or default_encoder()
        self.state = state
        self.data, self.name = state_proxies(
            dataclass_type,
            state,
            state_namespace=state_namespace,
            state_encoder=self._encoder,
        )

    @singledispatchmethod
    def bind_change(
        self, key: Any | list[Any] | tuple[Any], callback: Callable
    ) -> None:
        """
        Binds a typed state key change to the given input callback.
        Calls are strongly typed and will call the passed callback only with the input keys and not the full trame
        state.

        Binding is compatible with nested dataclass types.

        :param key: The key or list of keys to bind to the callback. Keys should be taken from the self.name struct.
        :param callback: The callable taking one or more inputs.
        """
        bind_typed_state_change(key, callback, self.state, self.data)

    @bind_change.register
    def _(self, change_dict: dict) -> None:
        """
        Overload implementation for bind_change.
        Will unpack the input change dictionary and call the bind_change method for each key/value pair.

        :param change_dict:
        :type change_dict: dict[Any | list[Any], Callable]
        """
        for key, callback in change_dict.items():
            self.bind_change(key, callback)

    def encode(self, value: Any) -> Any:
        """
        Encodes the input value with the typed_state state encoder.
        """
        return self._encoder.encode(value)
