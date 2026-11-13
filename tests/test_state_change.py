import asyncio

import pytest

from trame_server import Server
from trame_server.core import Translator
from trame_server.state import State


@pytest.mark.asyncio
async def test_change_exception(fake_server):
    """
    0 msg  : test_change_exception
    1 push : {'a': 2}
    2 msg  : a changed (1)
    3 msg  : a changed (ValueError)
    4 msg  : a changed (2)
    5 push : {'a': 3}
    6 msg  : a changed (1)
    7 msg  : a changed (ValueError)
    8 msg  : a changed (2)
    """
    # fake_server = FakeServer()
    fake_server.add_event("test_change_exception")
    state = fake_server.state
    state.ready()

    state.a = 1

    @state.change("a")
    def change_a_ok_1(**__kwargs):
        fake_server.add_event("a changed (1)")

    @state.change("a")
    def change_a_exception(**__kwargs):
        fake_server.add_event("a changed (ValueError)")
        raise ValueError()

    @state.change("a")
    def change_a_ok_2(**__kwargs):
        fake_server.add_event("a changed (2)")

    with state:
        state.a = 2

    await asyncio.sleep(0.1)

    with state:
        state.a = 3

    await asyncio.sleep(0.1)

    result = [line.strip() for line in str(fake_server).split("\n")]
    expected = [line.strip() for line in str(test_change_exception.__doc__).split("\n")]

    # Grab new scenario output
    # print(expected)
    # print("-"*60)
    # print(result)

    assert expected == result


# -----------------------------------------------------------------------------
# Exception forwarding
# -----------------------------------------------------------------------------


def _ignored_errors(caplog):
    return [
        r
        for r in caplog.records
        if r.levelname == "ERROR" and "callback exception ignored" in r.message
    ]


def test_change_exception_forwarded_to_handler(caplog):

    reported = []
    executed = []

    def handler(exception):
        reported.append(exception)
        return True

    state = State(ready=True, exception_handler=handler)
    state.a = 1

    @state.change("a")
    def fail(**_):
        executed.append("fail")
        msg = "boom"
        raise ValueError(msg)

    @state.change("a")
    def ok(**_):
        executed.append("ok")

    with state:
        state.a = 2

    assert executed == ["fail", "ok"]
    assert len(reported) == 1
    assert isinstance(reported[0], ValueError)
    assert str(reported[0]) == "boom"
    assert reported[0].__traceback__ is not None
    assert len(_ignored_errors(caplog)) == 1


def test_change_exception_logged_without_handler(caplog):

    state = State(ready=True)
    state.a = 1

    @state.change("a")
    def fail(**_):
        raise ValueError()

    with state:
        state.a = 2

    records = _ignored_errors(caplog)
    assert len(records) == 1
    assert records[0].exc_info[0] is ValueError


def test_change_exception_logged_when_handler_declines(caplog):

    reported = []

    def handler(exception):
        reported.append(exception)
        return False

    state = State(ready=True, exception_handler=handler)
    state.a = 1

    @state.change("a")
    def fail(**_):
        raise ValueError()

    with state:
        state.a = 2

    assert len(reported) == 1
    assert len(_ignored_errors(caplog)) == 1


def test_change_exception_handler_failure_does_not_propagate(caplog):

    def handler(exception):
        raise RuntimeError() from exception

    state = State(ready=True, exception_handler=handler)
    state.a = 1

    @state.change("a")
    def fail(**_):
        raise ValueError()

    with state:
        state.a = 2

    assert any(
        r.levelname == "ERROR" and "Exception handler failed" in r.message
        for r in caplog.records
    )
    assert len(_ignored_errors(caplog)) == 1


@pytest.mark.asyncio
async def test_async_change_exception_forwarded_to_handler(caplog):

    reported = []

    def handler(exception):
        reported.append(exception)
        return True

    state = State(ready=True, exception_handler=handler)
    state.a = 1

    @state.change("a")
    async def fail(**_):
        await asyncio.sleep(0)
        msg = "async boom"
        raise ValueError(msg)

    with state:
        state.a = 2

    assert reported == []  # task not executed yet
    await asyncio.sleep(0.1)

    assert len(reported) == 1
    assert str(reported[0]) == "async boom"
    assert len(_ignored_errors(caplog)) == 1


@pytest.mark.asyncio
async def test_async_change_exception_logged_without_handler(caplog):

    state = State(ready=True)
    state.a = 1

    @state.change("a")
    async def fail(**_):
        raise ValueError()

    with state:
        state.a = 2

    await asyncio.sleep(0.1)
    assert len(_ignored_errors(caplog)) == 1


def test_child_state_inherits_exception_handler():

    reported = []

    def handler(exception):
        reported.append(exception)
        return True

    root = State(ready=True, exception_handler=handler)
    child = State(Translator(prefix="child_"), internal=root)
    child.a = 1

    @child.change("a")
    def fail(**_):
        raise ValueError()

    with child:
        child.a = 2

    assert len(reported) == 1


def test_server_change_exception_forwarded_to_on_exception(caplog):

    server = Server()
    server.state.ready()
    server.context.ready()

    reported = []
    server.controller.on_exception.add(reported.append)

    @server.state.change("a")
    def state_fail(a, **_):
        if a:
            msg = "state"
            raise ValueError(msg)

    @server.context.change("b")
    def context_fail(b, **_):
        if b:
            msg = "context"
            raise ValueError(msg)

    server.state.a = 1
    server.state.flush()
    server.context.b = 1
    server.context.flush()

    assert [str(e) for e in reported] == ["state", "context"]
    assert len(_ignored_errors(caplog)) == 2


def test_child_server_change_exception_forwarded_to_root_on_exception():

    server = Server()
    server.state.ready()
    child = server.create_child_server(prefix="child_")

    reported = []
    server.controller.on_exception.add(reported.append)

    @child.state.change("a")
    def fail(a, **_):
        if a:
            raise ValueError()

    child.state.a = 1
    child.state.flush()

    assert len(reported) == 1


def test_server_change_exception_logged_without_on_exception(caplog):

    server = Server()
    server.state.ready()

    @server.state.change("a")
    def fail(a, **_):
        if a:
            raise ValueError()

    server.state.a = 1
    server.state.flush()

    assert len(_ignored_errors(caplog)) == 1
