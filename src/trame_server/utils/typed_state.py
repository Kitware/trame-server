import inspect
from abc import ABC, abstractmethod
from dataclasses import MISSING, Field, fields, is_dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Type,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from trame_server.state import State

T = TypeVar("T")
V = TypeVar("V")


class _SerializationFailure:
    """
    Simple class to handle encoding / decoding failures
    """

    def __init__(self, reason: str = ""):
        self.reason = reason

    def __eq__(self, other):
        return isinstance(other, _SerializationFailure)


class IStateEncoderDecoder(ABC):
    """
    State to/from primitive type encoding/decoding interface.
    """

    _failure = _SerializationFailure()

    @abstractmethod
    def encode(self, obj):
        pass

    @abstractmethod
    def decode(self, obj, obj_type: type):
        pass

    @staticmethod
    def failed_serialization(reason: str = "") -> _SerializationFailure:
        return _SerializationFailure(reason)

    @classmethod
    def is_serialization_success(cls, value):
        return not isinstance(value, _SerializationFailure)


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
        if isinstance(obj, Path):
            return obj.as_posix()
        return obj

    def decode(self, obj, obj_type: type):
        if obj is None:
            return None
        if isinstance(obj, obj_type):
            return obj
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
    Encoding/decoding for lists, tuples, dicts and type unions. Delegates to an encoder list for contained types.
    Expects the encoder in its encoder list to return self.failed_serialization when encoding / decoding a specific
    type is not possible.
    If the delegate encoder raises an error, the error will be caught and considered as failed_serialization.
    Encoder will continue to the following encoder if the previous one wasn't able to encode / decode it.

    :param encoders: List of encoders to use when encoding/decoding lists and dicts.
    """

    def __init__(self, encoders: list[IStateEncoderDecoder] | None = None):
        self._encoders = encoders or [DefaultEncoderDecoder()]

    def encode(self, obj):
        if is_dataclass(obj):
            return {
                field.name: self.encode(getattr(obj, field.name))
                for field in fields(obj)
            }

        if isinstance(obj, dict):
            return {self.encode(key): self.encode(value) for key, value in obj.items()}

        if self._is_iterable(obj):
            return type(obj)(self.encode(value) for value in obj)

        for encoder in self._encoders:
            val = self._try_serialize(encoder.encode, obj)
            if self.is_serialization_success(val):
                return val

        _error_msg = f"Failed to encode object {obj}. No appropriate encoder in {self._encoders}."
        raise TypeError(_error_msg)

    @classmethod
    def _is_iterable(cls, obj):
        return isinstance(obj, list) or isinstance(obj, tuple)

    def _try_serialize(self, f, *args):
        try:
            return f(*args)
        except Exception as e:
            return self.failed_serialization(str(e))

    def decode(self, obj, obj_type: type):
        val = self._try_decode(obj, obj_type)
        if self.is_serialization_success(val):
            return val

        _error_msg = f"Failed to decode object {obj} of type {obj_type}. No appropriate decoder in {self._encoders}."
        raise TypeError(_error_msg)

    def _try_decode(self, obj, obj_type: type):
        for decode in self._decode_strategies():
            val = decode(obj, obj_type)
            if self.is_serialization_success(val):
                return val
        return self.failed_serialization()

    def _decode_strategies(self) -> list[Callable[[Any, type], Any]]:
        return [
            self._decode_dataclass,
            self._decode_union,
            self._decode_dict,
            self._decode_iterable,
            self._delegate_decode,
        ]

    def _delegate_decode(self, obj, obj_type: type):
        for encoder in self._encoders:
            val = self._try_serialize(encoder.decode, obj, obj_type)
            if self.is_serialization_success(val):
                return val
        return self.failed_serialization()

    def _decode_dict(self, obj, obj_type: type):
        if not isinstance(obj, dict):
            return self.failed_serialization()

        key_type, value_type = get_args(obj_type)
        return {
            self.decode(key, key_type): self.decode(value, value_type)
            for key, value in obj.items()
        }

    def _decode_iterable(self, obj, obj_type: type):
        if not self._is_iterable(obj):
            return self.failed_serialization()

        value_type = get_args(obj_type)[0]
        return obj_type(self.decode(value, value_type) for value in obj)

    def _decode_union(self, obj, obj_type: type):
        if not self._is_union_type(obj_type):
            return self.failed_serialization()

        for sub_union_type in get_args(obj_type):
            val = self._try_decode(obj, sub_union_type)
            if self.is_serialization_success(val):
                return val
        return self.failed_serialization()

    def _decode_dataclass(self, obj, obj_type: type):
        if not is_dataclass(obj_type):
            return self.failed_serialization()

        field_types = get_type_hints(obj_type)
        decoded_dict = {
            field.name: self._try_decode(obj.get(field.name), field_types[field.name])
            for field in fields(obj_type)
        }
        return obj_type(**decoded_dict)

    @classmethod
    def _is_union_type(cls, obj_type: type):
        return get_origin(obj_type) is Union or isinstance(obj_type, UnionType)


class _ProxyField:
    """
    Descriptor for proxy state fields to an equivalent dataclass field.
    If the dataclass provides default, or a default factory, the associated state will be initialized to the given
    encoded state value.

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


class _NameField:
    """
    Descriptor for fields to state id string equivalent.

    :param state_id: Associated trame string id where the data will be pushed / read from.
    """

    def __init__(self, state_id: str):
        self._state_id = state_id

    def __get__(self, instance, owner):
        return self._state_id


class TypedState(Generic[T]):
    """
    Helper to have access to, mutate, and be notified of state changes using a strongly typed dataclass interface.

    TypedState provides a type-safe wrapper around the trame State object, allowing to:
    - Access and modify state using dataclass field names with full type hints
    - Bind change callbacks to specific fields or combinations of fields
    - Automatically handle encoding/decoding of complex types (enums, UUIDs, dates, etc.)
    - Use namespaces to avoid conflicts between different state objects
    """

    _STATE_PROXY_DATACLASS_TYPE = "__state_proxy_dataclass_type"
    _STATE_PROXY_FIELD_DICT = "__state_proxy_field_dict"
    _STATE_PROXY_STATE_ID = "__state_proxy_state_id"

    def __init__(
        self,
        state: State,
        dataclass_type: Type[T],
        *,
        namespace="",
        encoders: list[IStateEncoderDecoder] | None = None,
        encoder: IStateEncoderDecoder | None = None,
        data: T | None = None,
        name: T | None = None,
    ):
        self._encoder = encoder or CollectionEncoderDecoder(encoders)
        self.state = state
        self.data = data or self._create_state_proxy(
            dataclass_type=dataclass_type,
            state=state,
            namespace=namespace,
            encoder=self._encoder,
        )

        self.name = name or self._create_state_names_proxy(
            dataclass_type=dataclass_type,
            namespace=namespace,
        )

    def bind_changes(
        self, change_dict: dict[Any | list[Any] | tuple[Any], Callable]
    ) -> None:
        """
        Binds a typed state key change to the given input callback.
        Calls are strongly typed and will call the passed callback only with the input keys and not the full trame
        state.

        Binding is compatible with nested dataclass types.

        :param change_dict: Dict containing the key to callback mapping to bind.
        """
        for key, callback in change_dict.items():
            self.bind_typed_state_change(key, callback, self.state, self.data)

    def encode(self, value: Any) -> Any:
        """
        Encodes the input value with the typed_state state encoder.
        """
        return self._encoder.encode(value)

    def get_dataclass(self) -> T:
        """
        :return: Current content of the typed state as dataclass.
        """
        return self.as_dataclass(self.data)

    def set_dataclass(self, data: T) -> None:
        """
        Set the content of the typed state from the input dataclass.
        Dataclass instance needs to match the dataclass type the typed state was constructed from.
        :param data: Instance of dataclass matching the typed state type.
        """
        self.from_dataclass(self.data, data)

    @classmethod
    def _create_state_proxy(
        cls,
        dataclass_type: Type[T],
        state: State,
        *,
        namespace="",
        encoder: IStateEncoderDecoder | None = None,
    ) -> T:
        """
        Returns a State proxy with the same field structure as the input dataclass and for each field returning a proxy
        to the associated state value.

        :param dataclass_type: Type of dataclass for which the proxy will be created.
        :param state: Trame state which will be mutated/read from by the proxy.
        :param namespace: Optional namespace for the trame state. All proxy field access will be using this
            namespace prefix.
        :param encoder: Optional encoder/decoder from dataclass field to trame state field. If not encoder is
            provided, will use a default encoder/decoder.
        """
        encoder = encoder or CollectionEncoderDecoder(None)

        def handler(state_id: str, field: Field, field_type: type):
            return _ProxyField(
                state=state,
                state_id=state_id,
                name=field.name,
                default=field.default,
                default_factory=field.default_factory,
                field_type=field_type,
                state_encoder=encoder,
            )

        return cls._build_proxy_cls(dataclass_type, namespace, handler, "__Proxy")

    @classmethod
    def _create_state_names_proxy(cls, dataclass_type: Type[T], *, namespace="") -> T:
        """
        Returns a State proxy with the same field structure as the input dataclass and for each field returning the
        fully qualified state id name associated with a dataclass leaf.

        :param dataclass_type: Type of dataclass for which the proxy will be created.
        :param namespace: Optional namespace for the trame state. All proxy field access will be using this
            namespace prefix.
        """

        def handler(state_id: str, _field: Field, _field_type: type):
            return _NameField(state_id=state_id)

        return cls._build_proxy_cls(dataclass_type, namespace, handler, "__ProxyName")

    @classmethod
    def _build_proxy_cls(
        cls,
        dataclass_type: Type[T],
        prefix: str,
        handler: Callable[[str, Field, type], Any],
        cls_suffix: str,
        proxy_field_dict: dict | None = None,
    ) -> T:
        """
        Parses the input dataclass_type fields and construct a dataclass proxy based on its Field
        hierarchy. Visits each Field and nested dataclass recursively and forwards proxy field creation to the handler
        callable.

        :param dataclass_type: Type of the dataclass for which the proxy will be created
        :param prefix: State id prefix for each field created from the dataclass.
        :param handler: Callable which is responsible for creating the proxy attached in place of each Field.
        :param cls_suffix: Suffix attached to the created Proxy class type.
        :param proxy_field_dict: Dict of proxy fields at the parent level. Leave as None when starting recursion.
        :return: Created Proxy instance.
        """
        namespace = {}
        class_name = dataclass_type.__name__
        inner_field_dict = {}
        prefix = f"{prefix}__{class_name}" if prefix else class_name

        # Use type hints instead of field.type to avoid lazy evaluation of field.type when used in files containing
        # from __future__ import annotations header.
        field_types = get_type_hints(dataclass_type)
        for f in fields(dataclass_type):
            state_id = f"{prefix}__{f.name}"
            f_type = field_types[f.name]
            if is_dataclass(f_type):
                field = cls._build_proxy_cls(
                    f_type, state_id, handler, cls_suffix, inner_field_dict
                )
            else:
                field = handler(state_id, f, f_type)

            inner_field_dict[cls.get_state_id(field, state_id)] = field
            namespace[f.name] = field

        if proxy_field_dict is not None:
            proxy_field_dict.update(**inner_field_dict)

        # Add dataclass type, fields and state id to the proxy class
        namespace[cls._STATE_PROXY_DATACLASS_TYPE] = dataclass_type
        namespace[cls._STATE_PROXY_FIELD_DICT] = inner_field_dict
        namespace[cls._STATE_PROXY_STATE_ID] = prefix
        proxy_cls = type(f"{class_name}{cls_suffix}", (), namespace)

        # Create the proxy instance and add instance to the accessible proxy fields
        proxy_instance = proxy_cls()
        inner_field_dict[prefix] = proxy_instance
        return cast(T, proxy_instance)

    @classmethod
    def _get_proxy_dataclass_type(cls, instance: T) -> Type[T] | None:
        """
        :return: dataclass type attached to the input proxy instance.
        """
        return getattr(instance, cls._STATE_PROXY_DATACLASS_TYPE, None)

    @classmethod
    def _get_proxy_dataclass_type_or_raise(cls, instance: T) -> Type[T]:
        """
        :return: dataclass type attached to the proxy instance
        :raises: RuntimeError if the input instance is not a proxy.
        """
        kls = cls._get_proxy_dataclass_type(instance)
        if kls is None:
            _error_msg = (
                f"Expected an instance of type __Proxy got {type(instance).__name__}."
            )
            raise RuntimeError(_error_msg)
        return kls

    @classmethod
    def is_proxy_class(cls, instance: T) -> bool:
        """
        :return: True if the input instance is a state proxy type. False otherwise.
        """
        return cls._get_proxy_dataclass_type(instance) is not None

    @classmethod
    def is_name_proxy_class(cls, instance: T) -> bool:
        return cls.is_proxy_class(instance) and type(instance).__name__.endswith(
            "__ProxyName"
        )

    @classmethod
    def is_data_proxy_class(cls, instance: T) -> bool:
        return cls.is_proxy_class(instance) and type(instance).__name__.endswith(
            "__Proxy"
        )

    @classmethod
    def get_state_id(cls, instance: T, default: str = "") -> str:
        """
        :return: State id string attached to the input state proxy or default if the input is not a state proxy
            instance.
        """
        return getattr(instance, cls._STATE_PROXY_STATE_ID, default)

    @classmethod
    def as_dataclass(cls, instance: T) -> T:
        """
        Converts the input state proxy instance to dataclass.
        """
        dataclass_type = cls._get_proxy_dataclass_type_or_raise(instance)

        kwargs = {}
        for f in fields(dataclass_type):
            attr = getattr(instance, f.name)
            if cls.is_proxy_class(attr):
                kwargs[f.name] = cls.as_dataclass(attr)
            else:
                kwargs[f.name] = attr

        return dataclass_type(**kwargs)

    @classmethod
    def from_dataclass(cls, instance: T, dataclass_obj: T) -> None:
        """
        Populate the state proxy instance from the values of the given dataclass object.
        """
        dataclass_type = cls._get_proxy_dataclass_type_or_raise(instance)

        if not isinstance(dataclass_obj, dataclass_type):
            _error_msg = f"Expected instance of {dataclass_type.__name__}, got {type(dataclass_obj).__name__}"
            raise TypeError(_error_msg)

        for f in fields(dataclass_type):
            attr = getattr(instance, f.name)
            value = getattr(dataclass_obj, f.name)

            if cls.is_proxy_class(attr):
                cls.from_dataclass(attr, value)
            else:
                setattr(instance, f.name, value)

    @classmethod
    def get_field_proxy_dict(cls, instance: T) -> dict[str, _ProxyField]:
        """
        :returns: State ID to ProxyField as saved in the input instance.
        """
        cls._get_proxy_dataclass_type_or_raise(instance)
        return getattr(instance, cls._STATE_PROXY_FIELD_DICT, {})

    @classmethod
    def get_reactive_state_id_keys(cls, keys: Iterable[Any]) -> list[str]:
        """
        returns the list of state ids to react to on change from the input.

        :param keys: tuple of either str or dataclass proxy.
        :return: list of keys
        """
        react_keys = []
        for key in keys:
            if cls.is_proxy_class(key):
                react_keys.extend(list(cls.get_field_proxy_dict(key).keys()))
            else:
                react_keys.append(key)
        return react_keys

    @classmethod
    def get_value_state_keys(cls, keys: Iterable[Any]) -> list[str]:
        """
        returns the list of keys in the proxy to return when the state modified a given key.

        :param keys: tuple of either str or dataclass proxy.
        :return: list of keys present in the proxy instance field dict
        """

        return [cls.get_state_id(key, key) for key in keys]

    @classmethod
    def bind_typed_state_change(
        cls,
        keys: Any | list[Any] | tuple[Any],
        callback: Callable,
        state: State,
        data: T,
    ) -> None:
        """
        Bind state id changes to callbacks.
        Callbacks are called with converted state values found with input keys.
        """
        state_id_to_field_dict = cls.get_field_proxy_dict(data)

        if isinstance(keys, list):
            keys = tuple(keys)

        if not isinstance(keys, tuple):
            keys = (keys,)

        value_keys = cls.get_value_state_keys(keys)

        # On state change, get strongly typed values from the typed state and call the callback with the given values
        def _on_state_change(**_):
            values = [state_id_to_field_dict[k] for k in value_keys]
            values = [v if cls.is_proxy_class(v) else v.get_value() for v in values]
            return callback(*values)

        # Define an async variant for state change in case the bound method is async
        async def _on_state_change_async(**_):
            await _on_state_change()

        # Use state change closure to bind to direct or async version depending on the bound callback
        state.change(*cls.get_reactive_state_id_keys(keys))(
            _on_state_change_async
            if inspect.iscoroutinefunction(callback)
            else _on_state_change
        )

    def get_sub_state(self, sub_name: V) -> "TypedState[V]":
        """
        Create a TypedState based on a sub nested dataclass name proxy.
        The created TypedState will have the same state ids as the ones present in the full TypedState.
        This method can be used to simplify the connection of a "full" TypedState to sub UI components such as buttons
        or sliders.

        :returns: New typed state based on the given input sub name.
        """
        if not self.is_name_proxy_class(sub_name):
            _error_msg = f"Sub state creation should be called with a Name Proxy instance. Got: {type(sub_name)}"
            raise RuntimeError(_error_msg)

        state_id = self.get_state_id(sub_name)
        sub_data = self.get_field_proxy_dict(self.data)[state_id]
        return TypedState(
            self.state,
            self._get_proxy_dataclass_type(sub_name),
            encoder=self._encoder,
            data=sub_data,
            name=sub_name,
        )
