import pytest

from trame_server import Server


@pytest.fixture(scope="session")
def server():
    return Server()


@pytest.fixture
def controller(server):
    return server.controller
