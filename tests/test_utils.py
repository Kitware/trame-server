import io
import pytest
import asyncio
from contextlib import redirect_stdout
from trame_server import utils
from trame_server.utils import version, banner, server, hot_reload
from trame.app import get_server


def test_banner():
    with io.StringIO() as buf, redirect_stdout(buf):
        banner.print_banner()
        output = buf.getvalue()
        assert len(output) > 4096


@pytest.mark.asyncio
async def test_print_informations():
    server_app = get_server("test_print_informations")

    with io.StringIO() as buf, redirect_stdout(buf):
        server_app.start(exec_mode="task", port=0)
        assert await server_app.ready

        # not automatic when server start as task
        server.print_informations(server_app)
        output = buf.getvalue()
        assert "http://localhost:" in output

        await asyncio.sleep(0.1)
        await server_app.stop()


def test_version():
    from trame_server import __version__ as v_server
    from trame_client import __version__ as v_client

    assert version.get_version("trame_server") == v_server
    assert version.get_version("trame_client") == v_client
    assert version.get_version("trame").split(".")[0] == "3"
    assert version.get_version("something_that_does_not_exist") is None


def test_utils_fn():
    assert utils._isascii_36(b"sdv")
    assert utils._isascii_36("sdv")
    assert not utils._isascii_36("Hällö, Wörld!")

    # remove filter keys
    input_dict = {"a": "hello", "b": "world", "_filter": ["b"]}
    output_dict = utils.clean_value(input_dict)
    assert input_dict != output_dict
    assert output_dict == {"a": "hello", "_filter": ["b"]}

    # deep clone
    input_dict = {
        "a": {
            "a.a": {"x": 1},
            "a.b": {"y": 2},
        },
        "b": {
            "b.a": {"z": 3},
            "b.b": {"xyz": 4},
        },
    }
    output_dict = {}
    utils.update_dict(output_dict, input_dict)
    assert output_dict == input_dict
    assert input_dict["a"] is input_dict["a"]
    assert output_dict["a"] == input_dict["a"]
    assert output_dict["a"] is not input_dict["a"]
    assert output_dict["a"]["a.a"] == input_dict["a"]["a.a"]
    assert output_dict["a"]["a.a"] is not input_dict["a"]["a.a"]

    # reduce vue_use
    class FakeState:
        def __init__(self):
            self.trame__vue_use = [
                "trame_vtk",
                ("hello", {"a": 1, "c": {"x": 1}}),
                "trame_vtk",
                ("hello", {"b": 2, "c": {"y": 2}}),
                "trame_vtk",
                "trame_xyz",
            ]

    fake_state = FakeState()
    utils.reduce_vue_use(fake_state)
    assert fake_state.trame__vue_use == [
        "trame_vtk",
        (
            "hello",
            {
                "a": 1,
                "b": 2,
                "c": {
                    "x": 1,
                    "y": 2,
                },
            },
        ),
        "trame_xyz",
    ]


def test_hot_reload():
    @hot_reload.hot_reload
    def re_eval():
        pass

    # skip decorate twice
    hot_reload.hot_reload(re_eval)

    re_eval()
