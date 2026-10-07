import asyncio
import importlib
import io
import socket
import sys
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock

import more_itertools
import pytest

from trame_server.ui import VirtualNodeManager
from trame_server.utils import browser, hot_reload, logger, server
from trame_server.utils.argument_parser import ArgumentParser

# -----------------------------------------------------------------------------
# logger
# -----------------------------------------------------------------------------


@pytest.fixture
def network_log(tmp_path):
    log_file = tmp_path / "network.log"
    log_file.write_text("previous run")
    logger.initialize_logger({"log_network": str(log_file)})
    try:
        yield log_file
    finally:
        logger.initialize_logger({})


def test_logger_disabled(tmp_path, capsys):
    logger.initialize_logger({})
    logger.state_c2s({"a": 1})
    logger.error("nothing written")
    assert "Error: nothing written" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_logger_enabled(network_log, capsys):
    # Previous log removed at initialization
    assert not network_log.exists()

    logger.initial_state({"init": 1})
    logger.state_c2s({"c2s": 2})
    logger.state_s2c({"s2c": b"binary"})
    logger.action_c2s({"name": "click"})
    logger.action_s2c({"type": "action"})
    logger.error("something broke")

    content = network_log.read_text()
    assert logger.StateExchangeType.STATE_INITIAL in content
    assert logger.StateExchangeType.STATE_CLIENT_TO_SERVER in content
    assert logger.StateExchangeType.STATE_SERVER_TO_CLIENT in content
    assert logger.StateExchangeType.ACTION_CLIENT_TO_SERVER in content
    assert logger.StateExchangeType.ACTION_SERVER_TO_CLIENT in content
    assert "<class 'bytes'>" in content
    assert "ERROR: something broke" in content
    assert "Error: something broke" in capsys.readouterr().out

    with pytest.raises(TypeError):
        logger.state_c2s({"not_serializable": object()})


# -----------------------------------------------------------------------------
# argument_parser
# -----------------------------------------------------------------------------


def test_argument_parser_env(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py", "--ignored"])
    monkeypatch.setenv("TRAME_ARGS", "-p 8081 --server")
    parser = ArgumentParser()
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("--server", action="store_true")
    args, unknown = parser.parse_known_args()
    assert args.port == 8081
    assert args.server
    assert unknown == []


@pytest.mark.parametrize(
    "argv",
    [
        ["app.py", "--trame-args=-p 8082 --server"],
        ["app.py", "--", "--trame-args", "-p 8082 --server"],
    ],
)
def test_argument_parser_trame_args(monkeypatch, argv):
    monkeypatch.delenv("TRAME_ARGS", raising=False)
    monkeypatch.setattr(sys, "argv", argv)
    parser = ArgumentParser()
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("--server", action="store_true")
    args, _ = parser.parse_known_args()
    assert args.port == 8082
    assert args.server


# -----------------------------------------------------------------------------
# browser / server information
# -----------------------------------------------------------------------------


def _fake_server(host="localhost", port=1234):
    cli = ArgumentParser()
    cli.add_argument("--host", default=host)
    return SimpleNamespace(
        cli=cli,
        port=port,
        server_options=Namespace(host=host),
    )


@pytest.mark.asyncio
async def test_open_browser(monkeypatch):
    import webbrowser  # noqa: PLC0415

    open_mock = MagicMock()
    monkeypatch.setattr(webbrowser, "open", open_mock)

    with io.StringIO() as buf, redirect_stdout(buf):
        browser.open_browser(_fake_server())
        assert "--server" in buf.getvalue()

    await asyncio.sleep(0.2)
    open_mock.assert_called_once_with("http://localhost:1234/")


def test_open_browser_error(monkeypatch):
    def fail():
        raise RuntimeError

    monkeypatch.setattr(asyncio, "get_event_loop", fail)
    # Errors are silently ignored
    browser.open_browser(_fake_server())


def test_print_informations_host_fallback(monkeypatch):
    calls = []

    def gethostbyname(name):
        calls.append(name)
        if name == "unknown-host":
            raise OSError
        return "10.0.0.1"

    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)
    monkeypatch.setattr(socket, "gethostname", lambda: "my-machine")

    with io.StringIO() as buf, redirect_stdout(buf):
        server.print_informations(_fake_server(host="unknown-host"))
        output = buf.getvalue()

    assert calls == ["unknown-host", "my-machine"]
    assert "Network: http://10.0.0.1:1234/" in output


def test_print_informations_no_network(monkeypatch):
    def gethostbyname(_):
        raise socket.gaierror

    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)

    with io.StringIO() as buf, redirect_stdout(buf):
        server.print_informations(_fake_server(host="nowhere"))
        assert "Network: http://nowhere:1234/" in buf.getvalue()


# -----------------------------------------------------------------------------
# ui
# -----------------------------------------------------------------------------


def test_virtual_node_manager():
    manager = VirtualNodeManager("fake_server")
    with pytest.raises(AttributeError):
        _ = manager.__not_existing__

    created = []

    def constructor(trame_server):
        created.append(trame_server)
        return MagicMock()

    manager.set_vn_constructor(constructor)
    assert manager.content is manager["content"]
    assert created == ["fake_server"]


# -----------------------------------------------------------------------------
# hot_reload
# -----------------------------------------------------------------------------

MODULE_TEMPLATE = """
def ctrl(*_, **__):
    return lambda f: f

class Obj:
    def attr(self, *_):
        return lambda f: f

obj = Obj()

def extra(f):
    f.extra = True
    return f

@obj.attr("x")
@extra
@ctrl("y")
def compute(x):
    return x * {factor}

class Holder:
    def method(self):
        return {factor}
"""


@pytest.fixture
def reloadable_module(tmp_path, monkeypatch):
    path = tmp_path / "hr_sample_module.py"

    def write(factor):
        path.write_text(MODULE_TEMPLATE.format(factor=factor))

    write(1)
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("hr_sample_module")
    try:
        yield module, path, write
    finally:
        sys.modules.pop("hr_sample_module", None)


def test_reload_function_and_method(reloadable_module):
    module, _, write = reloadable_module
    holder = module.Holder()

    assert module.compute(3) == 3
    assert holder.method() == 1

    write(10)

    reloaded = hot_reload.reload(module.compute)
    assert reloaded(3) == 30
    assert reloaded.extra
    reloaded_method = hot_reload.reload(holder.method)
    assert reloaded_method.__self__ is holder
    assert reloaded_method() == 10


def test_reload_recovers_from_errors(reloadable_module, monkeypatch):
    module, path, write = reloadable_module
    holder = module.Holder()
    path.write_text("def broken(:\n")

    attempts = []

    def fix_file(func):
        attempts.append(func)
        if len(attempts) == 1:
            # Syntax valid, but function is missing
            path.write_text("def something_else():\n    pass\n")
        else:
            write(5)
        return True

    monkeypatch.setattr(hot_reload, "_handle_exception", fix_file)
    assert hot_reload.reload(holder.method)() == 5
    assert len(attempts) == 2


def test_reload_skips():
    assert hot_reload.reload(42) == 42

    fn = lambda: 1  # noqa: E731
    assert hot_reload.reload(fn) is fn

    # Function living in site-packages
    assert hot_reload.reload(more_itertools.first) is more_itertools.first

    # Methods of trame elements are skipped
    from trame_client.widgets.core import AbstractElement  # noqa: PLC0415

    class CustomElement(AbstractElement):
        def method(self):
            pass

    element = object.__new__(CustomElement)
    method = element.method
    assert hot_reload.reload(method) is method


def test_reload_nested_function_closure():
    captured_value = 7

    def nested_with_closure():
        return captured_value

    reloaded = hot_reload.reload(nested_with_closure)
    assert reloaded is not nested_with_closure
    assert reloaded() == 7


def test_hot_reload_decorator_stripping():
    import ast  # noqa: PLC0415

    tree = ast.parse(
        "@outer\n@hot_reload\n@ctrl.add('x')\n@keep\ndef fn():\n    pass\n"
    )
    assert hot_reload._isolate_function_def("fn", tree)
    names = [hot_reload._get_decorator_name(d) for d in tree.body[0].decorator_list]
    assert names == ["keep"]

    assert not hot_reload._isolate_function_def("missing", ast.parse("x = 1"))

    with pytest.raises(Exception, match="Failed to find decorator name"):
        hot_reload._get_decorator_name(ast.parse("(lambda f: f)").body[0].value)

    attr_dec = ast.parse("@state.change\ndef f(): pass").body[0].decorator_list[0]
    assert hot_reload._get_decorator_name(attr_dec) == "state"


class InteractiveInput(io.StringIO):
    def isatty(self):
        return True


def _handle_exception_output(monkeypatch, stdin):
    monkeypatch.setattr(sys, "stdin", stdin)

    def failing():
        pass

    out, err = io.StringIO(), io.StringIO()
    try:
        msg = "expected"
        raise ValueError(msg)
    except ValueError:
        with redirect_stdout(out), redirect_stderr(err):
            retry = hot_reload._handle_exception(failing)

    assert "ValueError: expected" in err.getvalue()
    return retry, out.getvalue()


def test_handle_exception_interactive(monkeypatch):
    retry, output = _handle_exception_output(monkeypatch, InteractiveInput("\n"))
    assert retry
    assert "press return to continue" in output

    # EOF (e.g. Ctrl-D) gives up
    retry, _ = _handle_exception_output(monkeypatch, InteractiveInput(""))
    assert not retry


@pytest.mark.parametrize("stdin", [None, io.StringIO("\n")])
def test_handle_exception_non_interactive(monkeypatch, stdin):
    retry, output = _handle_exception_output(monkeypatch, stdin)
    assert not retry
    assert "keeping previous version" in output
    assert "press return" not in output


def test_reload_keeps_function_when_non_interactive(reloadable_module, monkeypatch):
    module, path, _ = reloadable_module
    holder = module.Holder()
    path.write_text("def broken(:\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        reloaded = hot_reload.reload(holder.method)

    assert reloaded == holder.method
    assert reloaded() == 1
    assert "SyntaxError" in err.getvalue()
    # Reported once, not in a loop
    assert out.getvalue().count("keeping previous version") == 1


def test_load_file_waits_for_content(tmp_path, monkeypatch):
    path = tmp_path / "saving.py"
    path.write_text("")
    sleeps = []

    def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            path.write_text("x = 1")

    monkeypatch.setattr(hot_reload.time, "sleep", fake_sleep)
    assert hot_reload._load_file(path) == "x = 1\n"
    assert len(sleeps) == 3


def test_load_file_gives_up_on_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "empty.py"
    path.write_text("")
    sleeps = []
    monkeypatch.setattr(hot_reload.time, "sleep", sleeps.append)

    assert hot_reload._load_file(path) == "\n"
    assert len(sleeps) == hot_reload.EMPTY_FILE_RETRIES
