import asyncio
import logging
import weakref

import pytest

from trame_server.controller import FunctionNotImplementedError

logger = logging.getLogger(__name__)


def test_define_later(controller):
    f = controller.func
    with pytest.raises(FunctionNotImplementedError):
        f()

    controller.func = lambda: 3

    assert f() == 3


def test_trigger_name(controller):
    def fn_1(x):
        return x * 2

    def fn_2(x):
        return x * 3

    a_name = controller.trigger_name(fn_1)
    b_name = controller.trigger_name(fn_2)
    a_name_next = controller.trigger_name(fn_1)

    fn_1_r = controller.trigger_fn(a_name)
    fn_2_r = controller.trigger_fn(b_name)

    assert a_name != b_name
    assert a_name == a_name_next
    assert a_name == "trigger__1"
    assert fn_1 is fn_1_r
    assert fn_2 is fn_2_r


def test_composition(controller):
    def fn():
        return 1

    @controller.add("func_attr")
    def fn_1():
        return 1.5

    assert controller.func_attr() == [1.5]

    @controller.add("func_attr", clear=True)
    def fn_2():
        return 2

    @controller.once("func_attr")
    def fn_3():
        return 3

    # get
    f_attr = controller.func
    f_item = controller["func"]

    assert f_attr is f_item

    # set
    controller.func_attr = fn
    controller["func_item"] = fn

    assert controller.func_attr() == [1, 2, 3]
    assert controller.func_attr() == [1, 2]
    assert controller.func_attr() == [1, 2]

    # invalid set
    with pytest.raises(NameError):
        controller.trigger = fn


def test_weakrefs(controller):
    class Obj:
        method_call_count = 0
        destructor_call_count = 0

        def __del__(self):
            Obj.destructor_call_count += 1

        def fn(self):
            Obj.method_call_count += 1
            print("Obj.fn called")
            return 1

    o = Obj()

    controller.func.add(weakref.WeakMethod(o.fn))

    @controller.add("func")
    def fn_1():
        return 1.5

    controller.func()
    assert Obj.method_call_count == 1

    del o

    assert Obj.destructor_call_count == 1

    controller.func()
    assert Obj.method_call_count == 1


@pytest.mark.asyncio
async def test_tasks(controller):
    @controller.add("async_fn")
    def sync_fn_add():
        return 1

    @controller.add_task("async_fn", clear=True)
    async def async_fn():
        await asyncio.sleep(0.01)
        return 2

    @controller.add("async_fn")
    def sync_fn_add_2():
        return 4

    @controller.set("async_fn")
    def set_fn():
        return 5

    result = controller.async_fn()
    assert len(result) == 3
    assert result[0] == 5
    assert result[1] == 4
    assert await result[2] == 2

    result = controller.async_fn()
    assert len(result) == 3

    with pytest.raises(KeyError):
        controller.async_fn.remove(async_fn)
    controller.async_fn.remove_task(async_fn)

    result = controller.async_fn()
    assert len(result) == 2

    controller.async_fn.discard(async_fn)  # no error if missing
    controller.async_fn.discard(sync_fn_add_2)

    assert controller.async_fn() == 5

    @controller.set("async_fn", clear=True)
    def set_fn_2():
        return 10

    assert controller.async_fn() == 10
    assert controller.async_fn.exists()
    controller.async_fn.clear()
    assert not controller.async_fn.exists()


def test_child_controller(controller, server):
    child_server = server.create_child_server(prefix="child_")
    child_controller = child_server.controller

    @child_controller.add("func")
    def fn_1():
        return 1

    assert child_controller.func() == [1]

    @child_controller.add("func", clear=True)
    def fn_2():
        return 2

    @child_controller.once("func")
    def once_fn():
        return 2.5

    @child_controller.set("func")
    def fn_3():
        return 3

    assert child_controller.func() == [3, 2, 2.5]
    assert child_controller.func() == [3, 2]
    assert child_controller.func() == controller.child_func()
