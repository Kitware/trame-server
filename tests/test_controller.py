import pytest

from trame_server.controller import FunctionNotImplementedError


def test_define_later(controller):
    f = controller.func
    with pytest.raises(FunctionNotImplementedError):
        f()

    controller.func = lambda: 3

    assert f() == 3
