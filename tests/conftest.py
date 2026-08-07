import pytest

from trame_server import Server
from trame_server.core import Translator
from trame_server.state import State


@pytest.fixture(scope="session")
def server():
    return Server()


@pytest.fixture
def controller(server):
    return server.controller


class FakeServer:
    def __init__(self):
        self._change_callbacks = {}
        self._events = []
        self.translator = Translator()
        self.state = State(commit_fn=self._push_state, hot_reload=False)

    def _push_state(self, delta_state):
        self._events.append({"type": "push", "content": {**delta_state}})

    def add_event(self, content, type="msg"):
        self._events.append({"type": type, "content": content})

    @property
    def pushed_state(self) -> dict:
        pushed = {}
        for e in self._events:
            if e["type"] == "push":
                pushed.update(e["content"])
        return pushed

    def __repr__(self) -> str:
        lines = [""]
        for line_nb, entry in enumerate(self._events):
            lines.append(f"{line_nb:6} {entry.get('type'):5}: {entry.get('content')}")
        lines.append("")
        return "\n".join(lines)


@pytest.fixture
def fake_server():
    return FakeServer()
