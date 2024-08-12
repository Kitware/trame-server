import logging

import pytest

from trame_server import Server
from trame_server.controller import FunctionNotImplementedError
from trame_server.utils.namespace import Translator

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

    assert a_name != b_name
    assert a_name == a_name_next
    assert a_name == "trigger__1"
    assert b_name == "trigger__2"


def test_trigger_translator():
    prefix = "ctrl_test_prefix_"
    server = Server(translator=Translator(prefix))

    def func():
        return None

    trigger_name = server.controller.trigger_name(func)

    assert trigger_name == f"{prefix}trigger__1"
    assert server.controller.trigger_fn(trigger_name) == func

    server.controller.trigger_name(func) == trigger_name
