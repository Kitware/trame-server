from .utils import is_dunder, asynchronous


class Controller:
    """Controller acts as a container for function proxies

    It allows functions to be passed around that are not yet defined,
    and can be defined or re-defined later. For example:

    >>> ctrl.trigger_name(fn)
    trigger__12

    >>> f = ctrl.hello_func  # function is currently undefined
    >>> ctrl.hello_func = lambda: print("Hello, world!")
    >>> f()
    Hello, world!

    >>> ctrl.hello_func = lambda: print("Hello again!")
    >>> f()
    Hello again!

    >>> ctrl.on_data_change.add(lambda: print("Update pipeline!"))
    >>> ctrl.on_data_change.add(lambda: print("Update view!"))
    >>> ctrl.on_data_change.add(lambda: print("Wow that is pretty cool!"))
    >>> ctrl.on_data_change()
    "Update pipeline!"
    "Wow that is pretty cool!"
    "Update view!"
    >>> ctrl.on_data_change.clear(set_only=True) # add, remove, discard, clear
    """

    def __init__(self, trigger_decorator, trigger_name):
        super().__setattr__("_func_dict", {})
        self.trigger = trigger_decorator
        self.trigger_name = trigger_name

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __setitem__(self, name, value):
        self.__setattr__(name, value)

    def __getattr__(self, name):
        if is_dunder(name):
            return super().__getattr__(name)

        if name not in self._func_dict:
            self._func_dict[name] = ControllerFunction(name)

        return self._func_dict[name]

    def __setattr__(self, name, func):
        # Do not allow pre-existing attributes, such as `trigger`, to be
        # re-defined.
        if name in self.__dict__ or name in Controller.__dict__:
            msg = (
                f"'{name}' is a special attribute on Controller that cannot "
                "be re-assigned"
            )
            raise Exception(msg)

        if name in self._func_dict:
            self._func_dict[name].func = func
        else:
            self._func_dict[name] = ControllerFunction(name, func)

    def add(self, name, clear=False):
        """
        Use as decorator `@ctrl.add(name)` so the decorated function
        will be added to a given controller name

        :param name: Controller method name to be added to
        :type name: str

        .. code-block::

            ctrl = server.controller

            @ctr.add("on_server_ready")
            def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready.add(on_ready)

        You can also make sure when the method get registered we clear
        any previous content.

        .. code-block::

            ctrl = server.controller

            @ctr.add("on_server_ready", clear=True)
            def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready.clear()
            ctrl.on_server_ready.add(on_ready)

        """

        def register_ctrl_method(func):
            if clear:
                self[name].clear()

            self[name].add(func)
            return func

        return register_ctrl_method

    def add_task(self, name, clear=False):
        """
        Use as decorator `@ctrl.add_task(name)` so the decorated function
        will be added to a given controller name

        :param name: Controller method name to be added to
        :type name: str

        .. code-block::

            ctrl = server.controller

            @ctr.add_task("on_server_ready")
            async def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready.add_task(on_ready)

        You can also make sure when the method get registered we clear
        any previous content.

        .. code-block::

            ctrl = server.controller

            @ctr.add_task("on_server_ready", clear=True)
            async def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready.clear()
            ctrl.on_server_ready.add_task(on_ready)

        """

        def register_ctrl_method(func):
            if clear:
                self[name].clear()

            self[name].add_task(func)
            return func

        return register_ctrl_method

    def set(self, name, clear=False):
        """
        Use as decorator `@ctrl.set(name)` so the decorated function
        will be added to a given controller name

        :param name: Controller method name to be set to
        :type name: str

        .. code-block::

            ctrl = server.controller

            @ctr.set("on_server_ready")
            def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready = on_ready

        You can also make sure when the method get registered we clear
        any previous content.

        .. code-block::

            ctrl = server.controller

            @ctr.set("on_server_ready", clear=True)
            def on_ready(**state):
                pass

            # or
            ctrl.on_server_ready.clear()
            ctrl.on_server_ready = on_ready

        """

        def register_ctrl_method(func):
            if clear:
                self[name].clear()

            self[name] = func
            return func

        return register_ctrl_method


class ControllerFunction:
    """Controller functions are callable function proxy objects

    Any calls are forwarded to the internal function, which may be
    undefined or dynamically changed. If a call is made when the
    internal function is undefined, a FunctionNotImplementedError is
    raised.
    """

    def __init__(self, name, func=None):
        # The name is needed to provide more helpful information upon
        # a FunctionNotImplementedError exception.
        self.name = name
        self.func = func
        self.funcs = set()
        self.task_funcs = set()

    def __call__(self, *args, **kwargs):
        if self.func is None and len(self.funcs) == 0:
            raise FunctionNotImplementedError(self.name)

        copy_list = list(self.funcs)

        # Exec main function first
        result = None
        if self.func is not None:
            result = self.func(*args, **kwargs)

        # Exec added fn after
        results = list(map(lambda f: f(*args, **kwargs), copy_list))

        # Schedule any task
        for task_fn in list(self.task_funcs):
            asynchronous.create_task(task_fn(*args, **kwargs))

        # Figure out return
        if self.func is None:
            return results
        elif len(copy_list):
            return [result, *results]
        return result

    def add(self, func):
        """
        Add function to the set of functions to be called when
        the current ControllerFunction is called.

        :param func: Function to add
        """
        self.funcs.add(func)

    def add_task(self, func):
        """
        Add task to the set of coroutine to be called when
        the current ControllerFunction is called.

        :param func: Function to add
        """
        self.task_funcs.add(func)

    def discard(self, func):
        """
        Discard function to the set of functions to be called when
        the current ControllerFunction is called.

        :param func: Function to discard
        """
        self.funcs.discard(func)
        self.task_funcs.discard(func)

    def remove(self, func):
        """
        Remove function to the set of functions to be called when
        the current ControllerFunction is called.

        :param func: Function to remove
        """
        self.funcs.remove(func)

    def remove_task(self, func):
        """
        Remove task function to the set of functions to be called when
        the current ControllerFunction is called.

        :param func: Function to remove
        """
        self.task_funcs.remove(func)

    def clear(self, set_only=False):
        """
        Clear all the functions registered to the current ControllerFunction.

        :param set_only: (default: False) If true only the "added" one will be removed.
        """
        if not set_only:
            self.func = None

        self.funcs.clear()
        self.task_funcs.clear()

    def exists(self):
        """
        Check if at least a function was registered to the current ControllerFunction.

        :return: True if either a function was set or added
        """
        if self.func is not None:
            return True
        return len(self.funcs) + len(self.task_funcs) > 0


class FunctionNotImplementedError(Exception):
    pass
