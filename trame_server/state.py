from .utils import is_dunder, is_private

__all__ = [
    "State",
]


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

    def __init__(self, server):
        self._pending_update = {}
        self._pushed_state = {}
        #
        self._state_listeners = StateChangeHandler(server._change_callbacks)
        self._push_state_fn = server._push_state
        self._change = server.change

    def __getitem__(self, key):
        return self._pending_update.get(key, self._pushed_state.get(key))

    def __setitem__(self, key, value):
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
        return key in self._pushed_state

    def setdefault(self, key, value):
        """Set an initial value if the key is not present yet"""
        if key in self._pushed_state:
            return self._pushed_state[key]
        return self._pending_update.setdefault(key, value)

    def is_dirty(self, *_args):
        """
        Check if any provided key name(s) still has a pending
        changed that will need to be flushed.
        """
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
        for name in _args:
            if name in self._pending_update:
                count += 1

        return count == len(_args)

    def dirty(self, *_args):
        """
        Mark existing variable name(s) to be modified in a way that
        they will be pushed again at flush time.
        """
        for key in _args:
            self._pending_update.setdefault(key, self._pushed_state.get(key))

    def update(self, _dict):
        """Update the current state dict with the provided one"""
        self._pending_update.update(_dict)

    def flush(self):
        """Force pushing modified state and execute any @state.change listener"""
        keys = set()
        if len(self._pending_update):
            _keys = set(self._pending_update.keys())

            while len(_keys):
                keys |= _keys

                # Do the flush
                self._push_state_fn(self._pending_update)
                self._pushed_state.update(self._pending_update)
                self._pending_update = {}

                # Execute state listeners
                self._state_listeners.add_all(_keys)
                for callback in self._state_listeners:
                    callback(**self._pushed_state)
                self._state_listeners.clear()

                # Check if state change from state listeners
                _keys = set(self._pending_update.keys())

        return keys

    @property
    def change(self):
        """Function decorator for registering state change executions"""
        return self._change

    @property
    def initial(self):
        """Return the initial state without triggering a flush"""
        self._pushed_state.update(self._pending_update)
        self._pending_update = {}
        return self._pushed_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.flush()
