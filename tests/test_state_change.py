import asyncio

import pytest


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
