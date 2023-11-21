import inspect
import logging
from .utils import is_dunder, is_private, asynchronous, share
from .utils.hot_reload import reload
from .utils.namespace import Translator

logger = logging.getLogger(__name__)

__all__ = [
    "State",
]

TRAME_NON_INIT_VALUE = "__trame__: non_init_value_that_is_not_None"


class StateChangeHandler:
    def __init__(self, listeners):
        self._all_listeners = listeners
        self._currents = set()

    def add(self, key):
        if key in self._all_listeners:
            for callback in self._all_listeners[key]:
                self._currents.add(callback)

    def add_all(self, keys):
        for key in keys:
            self.add(key)

    def clear(self):
        self._currents.clear()

    def __iter__(self):
        return iter(list(self._currents))


class State:
    """
    Flexible dictionary managing a server shared state.
    Variables can be accessed with either the `[]` or `.` notation.
    """

    def __init__(
        self,
        translator=None,
        internal=None,
        commit_fn=None,
        hot_reload=False,
        ready=False,
    ):
        self._push_state_fn = commit_fn
        self._hot_reload = hot_reload
        self._translator = translator if translator else Translator()
        self._change_callbacks = share(internal, "_change_callbacks", {})
        self._pending_update = share(internal, "_pending_update", {})
        self._pushed_state = share(internal, "_pushed_state", {})
        #
        self._state_listeners = share(
            internal, "_state_listeners", StateChangeHandler(self._change_callbacks)
        )
        #
        self._parent_state = internal
        self._children_state = []
        self._ready_flag = ready
        if internal:
            internal._children_state.append(self)

    def ready(self):
        if self._ready_flag:
            return

        self._ready_flag = True
        self.flush()

        if self._parent_state:
            self._parent_state.ready()

        for child in self._children_state:
            child.ready()

    @property
    def is_ready(self):
        if self._parent_state:
            return self._parent_state.is_ready
        return self._ready_flag

    @property
    def translator(self):
        return self._translator

    def __getitem__(self, key):
        key = self._translator.translate_key(key)
        return self._pending_update.get(key, self._pushed_state.get(key))

    def __setitem__(self, key, value):
        key = self._translator.translate_key(key)
        if key in self._pushed_state:
            if value == self._pushed_state[key]:
                self._pending_update.pop(key, None)
                return

        self._pending_update[key] = value

    def __getattr__(self, key):
        if is_dunder(key):
            # Forward dunder calls to object
            return getattr(object, key)

        if is_private(key):
            return self.__dict__.get(key)

        return self.__getitem__(key)

    def __setattr__(self, key, value):
        if is_private(key):
            self.__dict__[key] = value
        else:
            self.__setitem__(key, value)

    def client_only(self, *_args):
        """
        Tag a given set of variable name(s) to be client only.
        This means that when they get changed on the client side,
        the server will not be aware of their change and no network
        bandwidth will be used to maintain the server in sync with
        the client state.

        :param *_args: A list a variable name
        :type *_args: str
        """
        _args = self._translator.translate_list(_args)
        change_detected = 0
        full_list = [
            *self._pending_update.get("trame__client_only", []),
            *self._pushed_state.get("trame__client_only", []),
        ]
        for name in _args:
            if name not in full_list:
                full_list.append(name)
                change_detected += 1

        if change_detected:
            self._pending_update["trame__client_only"] = full_list
            self.flush()

    def to_dict(self):
        """
        Flush current state modification and return the resulting
        state state as a python dict.
        """
        self.flush()
        return self._pushed_state

    def has(self, key):
        """Check is a key is currently available in the state"""
        _key = self._translator.translate_key(key)
        result = _key in self._pushed_state or _key in self._pending_update
        logger.info("has(%s => %s) = %s", key, _key, result)
        return result

    def setdefault(self, key, value):
        """Set an initial value if the key is not present yet"""
        key = self._translator.translate_key(key)
        if key in self._pushed_state:
            return self._pushed_state[key]
        return self._pending_update.setdefault(key, value)

    def is_dirty(self, *_args):
        """
        Check if any provided key name(s) still has a pending
        changed that will need to be flushed.
        """
        _args = self._translator.translate_list(_args)
        for name in _args:
            if name in self._pending_update:
                return True

        return False

    def is_dirty_all(self, *_args):
        """
        Check if all provided key name(s) has a pending
        changed that will need to be flushed.
        """
        count = 0
        _args = self._translator.translate_list(_args)
        for name in _args:
            if name in self._pending_update:
                count += 1

        return count == len(_args)

    def dirty(self, *_args):
        """
        Mark existing variable name(s) to be modified in a way that
        they will be pushed again at flush time.
        """
        _args = self._translator.translate_list(_args)
        for key in _args:
            self._pending_update.setdefault(key, self._pushed_state.get(key))

    def clean(self, *_args):
        """
        Save pending variable(s) and unmark them as dirty.
        This will prevent change listener(s) to react or the client
        to be aware of any change.
        """
        _args = self._translator.translate_list(_args)
        for key in _args:
            if key in self._pending_update:
                self._pushed_state[key] = self._pending_update.pop(key)

    def update(self, _dict):
        """Update the current state dict with the provided one"""
        _dict = self._translator.translate_dict(_dict)
        self._pending_update.update(_dict)
        for key in _dict:
            if _dict[key] == self._pushed_state.get(key, TRAME_NON_INIT_VALUE):
                self._pending_update.pop(key, None)

    def flush(self):
        """Force pushing modified state and execute any @state.change listener"""
        if not self.is_ready:
            return

        keys = set()
        if len(self._pending_update):
            _keys = set(self._pending_update.keys())

            while len(_keys):
                keys |= _keys

                # Do the flush
                if self._push_state_fn:
                    self._push_state_fn(self._pending_update)
                self._pushed_state.update(self._pending_update)
                self._pending_update.clear()

                # Execute state listeners
                self._state_listeners.add_all(_keys)
                for callback in self._state_listeners:
                    if self._hot_reload:
                        if not inspect.iscoroutinefunction(callback):
                            callback = reload(callback)

                    coroutine = callback(**self._pushed_state)
                    if inspect.isawaitable(coroutine):
                        asynchronous.create_task(coroutine)

                self._state_listeners.clear()

                # Check if state change from state listeners
                _keys = set(self._pending_update.keys())

        return keys

    @property
    def initial(self):
        """Return the initial state without triggering a flush"""
        self._pushed_state.update(self._pending_update)
        self._pending_update.clear()
        return self._pushed_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.flush()

    # -------------------------------------------------------------------------
    # Annotations
    # -------------------------------------------------------------------------

    def change(self, *_args, **_kwargs):
        """
        Use as decorator `@server.change(key1, key2, ...)` so the decorated function
        will be called like so `_fn(**state)` when any of the listed key name
        is getting modified from either client or server.

        :param *_args: A list of variable name to monitor
        :type *_args: str
        """

        def register_change_callback(func):
            for name in _args:
                name = self._translator.translate_key(name)
                if name not in self._change_callbacks:
                    self._change_callbacks[name] = []

                self._change_callbacks[name].append(func)
            return func

        return register_change_callback
