from .utils import is_dunder, is_private


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
        self.flush()
        return self._pushed_state

    def has(self, key):
        return key in self._pushed_state

    def setdefault(self, key, value):
        if key in self._pushed_state:
            return self._pushed_state[key]
        return self._pending_update.setdefault(key, value)

    def is_dirty(self, *_args):
        for name in _args:
            if name in self._pending_update:
                return True

        return False

    def is_dirty_all(self, *_args):
        count = 0
        for name in _args:
            if name in self._pending_update:
                count += 1

        return count == len(_args)

    def dirty(self, *_args):
        for key in _args:
            self._pending_update.setdefault(key, self._pushed_state.get(key))

    def update(self, _dict):
        self._pending_update.update(_dict)

    def flush(self):
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
        return self._change

    @property
    def initial(self):
        self._pushed_state.update(self._pending_update)
        self._pending_update = {}
        return self._pushed_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.flush()
