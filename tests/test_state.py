import asyncio
import weakref

import pytest

from trame_server.core import Translator
from trame_server.state import State


class FakeServer:
    def __init__(self):
        self._change_callbacks = {}
        self._events = []
        self.translator = Translator()

    def _push_state(self, delta_state):
        self._events.append({"type": "push", "content": {**delta_state}})

    def add_event(self, content, type="msg"):
        self._events.append({"type": type, "content": content})

    def __repr__(self) -> str:
        lines = [""]
        for line_nb, entry in enumerate(self._events):
            lines.append(f"{line_nb:6} {entry.get('type'):5}: {entry.get('content')}")
        lines.append("")
        return "\n".join(lines)


def test_minimum_change_detection():
    """
     0 msg  : test_minimum_change_detection
     1 msg  : Before server ready
     2 push : {'a': 2}
     3 exec : 2
     4 msg  : After server ready
     5 msg  : (prev=2) After 2, 3, 3, 4, 4
     6 msg  : (prev=4) Before Flush
     7 push : {'a': 4}
     8 exec : 4
     9 msg  : (prev=4) After Flush
    10 msg  : Enter with a=4
    11 msg  : About to exit a=4
    12 msg  : (prev=4) After with state + same value
    13 msg  : Enter with a=4
    14 msg  : About to exit a=5
    15 push : {'a': 5}
    16 exec : 5
    17 msg  : (prev=5) After with state + 3,4,5
    18 msg  : Enter with a=5
    19 msg  : About to exit a=5
    20 msg  : (prev=5) After with state + 3,5,4,5
    21 msg  : Enter with a=5
    22 msg  : About to exit a=5
    23 push : {'b': 3, 'c': 2}
    24 msg  : (prev=5) After with state + a:1,5 b:2,3 c:3,2
    25 msg  : Enter with a=5
    26 msg  : About to exit a=1
    27 push : {'a': 1, 'b': 2, 'c': 3}
    28 exec : 1
    """
    server = FakeServer()
    server.add_event("test_minimum_change_detection")
    state = State(commit_fn=server._push_state)

    @state.change("a")
    def on_change_exec(a, **_):
        server.add_event(type="exec", content=a)

    state.a = 1
    state.a = 1
    state.a = 2
    state.a = 2

    server.add_event("Before server ready")
    state.ready()
    server.add_event("After server ready")

    state.a = 2
    state.a = 3
    state.a = 3
    state.a = 4
    state.a = 4

    server.add_event("(prev=2) After 2, 3, 3, 4, 4")

    # Flush
    server.add_event("(prev=4) Before Flush")
    state.flush()
    server.add_event("(prev=4) After Flush")

    # This should be a NoOp
    with state:
        server.add_event(f"Enter with a={state.a}")
        state.a = 4
        server.add_event(f"About to exit a={state.a}")

    server.add_event("(prev=4) After with state + same value")

    with state:
        server.add_event(f"Enter with a={state.a}")
        state.a = 3
        state.a = 4
        state.a = 5
        server.add_event(f"About to exit a={state.a}")

    server.add_event("(prev=5) After with state + 3,4,5")

    # Even though it changed, finally it is the same value
    with state:
        server.add_event(f"Enter with a={state.a}")
        state.a = 3
        state.a = 5
        state.a = 4
        state.a = 5
        server.add_event(f"About to exit a={state.a}")

    server.add_event("(prev=5) After with state + 3,5,4,5")

    # Use update to set {a: 1, b: 2, c: 3}
    with state:
        server.add_event(f"Enter with a={state.a}")
        state.update({"a": 1, "b": 2, "c": 3})
        state.update({"a": 5, "b": 3, "c": 2})
        server.add_event(f"About to exit a={state.a}")

    server.add_event("(prev=5) After with state + a:1,5 b:2,3 c:3,2")

    # Use update to set {a: 1, b: 2, c: 3}
    with state:
        server.add_event(f"Enter with a={state.a}")
        state.update({"a": 1, "b": 2, "c": 3})
        server.add_event(f"About to exit a={state.a}")

    # Validate event
    result = [line.strip() for line in str(server).split("\n")]
    expected = [
        line.strip() for line in str(test_minimum_change_detection.__doc__).split("\n")
    ]

    # Grab new scenario output
    # print(expected)
    # print("-"*60)
    # print(result)

    assert expected == result


def test_client_only():
    server = FakeServer()
    server.add_event("test_client_only")
    state = State(commit_fn=server._push_state)
    state.ready()

    state.aa = 1
    state.client_only("aa")


def test_dict_api():
    server = FakeServer()
    server.add_event("test_dict_api")
    state = State(commit_fn=server._push_state)
    state.flush()  # should return right away since not ready
    state.ready()

    state.a = 1
    state.c = []
    assert state.has("a")
    assert not state.has("b")
    state.setdefault("a", 10)
    state.setdefault("b", 20)
    assert state.has("b")
    assert state.a == 1
    assert state.b == 20

    assert state.is_dirty_all("a", "b")
    assert state.is_dirty("a", "b")
    state.flush()
    assert not state.is_dirty("a", "b")
    assert state.setdefault("a", 30) == 1

    state.c.append("item")
    assert not state.is_dirty("c")
    state.dirty("c")
    assert state.is_dirty("c")

    assert state.initial == {"a": 1, "b": 20, "c": ["item"]}


@pytest.mark.asyncio
async def test_change_detection():
    """
    0 msg  : test_change_detection
    1 push : {'a': 2}
    2 msg  : a changed (sync)
    3 msg  : a changed (async)
    """
    server = FakeServer()
    server.add_event("test_change_detection")
    state = State(commit_fn=server._push_state, hot_reload=True)
    state.ready()

    state.a = 1

    @state.change("a")
    def regular_callback(**__kwargs):
        server.add_event("a changed (sync)")

    @state.change("a")
    async def coroutine_callback(**__kwargs):
        server.add_event("a changed (async)")

    assert "a" in state._pending_update
    state.clean("a")
    assert "a" not in state._pending_update

    with state:
        state.a = 2

    await asyncio.sleep(0.1)

    result = [line.strip() for line in str(server).split("\n")]
    expected = [line.strip() for line in str(test_change_detection.__doc__).split("\n")]

    # Grab new scenario output
    # print(expected)
    # print("-"*60)
    # print(result)

    assert expected == result


def test_dunder():
    server = FakeServer()
    server.add_event("test_dunder")
    state = State(commit_fn=server._push_state, hot_reload=True)
    state.ready()

    # get dunder
    assert state.__dict__ != state.__getattr__("__dict__")

    # get private (not in state)
    assert state._something is None

    # set private (not in state)
    state._something = 1
    assert state._something == 1

    state.flush()
    assert state.to_dict() == {}


@pytest.mark.asyncio
async def test_modified_keys():
    """
     0 msg  : test_modified_keys
     1 push : {'a': 1, 'b': 2, 'c': 3}
     2 msg  : get initial a,b,c
     3 msg  : changed should be => a
     4 push : {'a': 2}
     5 msg  : changed ['a']
     6 msg  : End of flush 1
     7 msg  : changed should be => a, b
     8 push : {'a': 3, 'b': 4}
     9 msg  : changed ['a', 'b']
    10 msg  : End of flush 2
    11 msg  : changed should be => a, b, c
    12 push : {'a': 4, 'b': 6, 'c': 6}
    13 msg  : changed ['a', 'b', 'c']
    14 msg  : side effect c => a + b
    15 push : {'a': 4.5, 'b': 6.5}
    16 msg  : changed ['a', 'b']
    17 msg  : End of flush 3
    """
    server = FakeServer()
    server.add_event("test_modified_keys")
    state = State(commit_fn=server._push_state)

    NAMES = ["a", "b", "c"]
    state.update(
        {
            "a": 1,
            "b": 2,
            "c": 3,
        }
    )
    state.ready()
    server.add_event("get initial a,b,c")
    await asyncio.sleep(0.01)

    @state.change(*NAMES)
    def on_change(**_):
        m_keys = list(state.modified_keys)
        m_keys.sort()
        server.add_event(f"changed {m_keys}")

    @state.change("c")
    def trigger_side_effect(**_):
        server.add_event("side effect c => a + b")
        state.a += 0.5
        state.b += 0.5

    with state:
        state.a += 1
        server.add_event("changed should be => a")

    # yield
    await asyncio.sleep(0.01)
    server.add_event("End of flush 1")

    with state:
        state.a += 1
        state.b += 2
        server.add_event("changed should be => a, b")

    # yield
    await asyncio.sleep(0.01)
    server.add_event("End of flush 2")

    with state:
        state.a += 1
        state.b += 2
        state.c += 3
        server.add_event("changed should be => a, b, c")

    # yield
    await asyncio.sleep(0.1)
    server.add_event("End of flush 3")

    result = [line.strip() for line in str(server).split("\n")]
    expected = [line.strip() for line in str(test_modified_keys.__doc__).split("\n")]

    # sometime 13 and 14 could have a reverse execution order
    # as trame does not guaranty the execution order of the callbacks.
    result.pop(14)
    result.pop(14)
    expected.pop(14)
    expected.pop(14)

    print(result)

    assert expected == result


def test_weakref():
    server = FakeServer()
    state = State(commit_fn=server._push_state, hot_reload=True)
    state.ready()

    class Obj:
        method_call_count = 0
        destructor_call_count = 0

        def __del__(self):
            Obj.destructor_call_count += 1

        def fn(self, *_args, **_kwargs):
            Obj.method_call_count += 1
            print("Obj.fn called")
            return 1

    o = Obj()

    state.a = 1

    state.change("a")(weakref.WeakMethod(o.fn))

    state.a = 2
    state.flush()
    assert Obj.method_call_count == 1

    del o
    assert Obj.destructor_call_count == 1

    state.a = 3
    state.flush()
    assert Obj.method_call_count == 1
