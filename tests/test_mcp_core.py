"""``server.mcp``: creation, options, first-class tools, resources and
prompts, and the launch options in ``Server.cli``."""

import itertools
import logging
from typing import Annotated

import aiohttp
import pytest
from trame.app import get_server

from trame_server.mcp import MCP, MCPDisabledError
from trame_server.mcp.objects import OBJECT_TOOLS

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)

_counter = itertools.count()


def new_server():
    return get_server(f"test_mcp_core_{next(_counter)}")


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def server():
    return new_server()


@pytest.fixture
def mcp(server):
    mcp = server.mcp
    mcp.enabled = True
    return mcp


async def start(server, **kwargs):
    server.start(
        exec_mode="task",
        port=0,
        open_browser=False,
        show_connection_info=False,
        disable_logging=True,
        **kwargs,
    )
    await server.ready


# -----------------------------------------------------------------------------
# Creation
# -----------------------------------------------------------------------------


def test_created_on_first_access_one_per_root_server(server):
    assert server._mcp is None
    mcp = server.mcp
    assert isinstance(mcp, MCP)
    assert server.mcp is mcp
    assert mcp.server is server
    assert mcp.protocol is mcp.protocol

    child = server.create_child_server(prefix="child_")
    assert child.mcp is child.mcp  # its root's, through its translator
    assert child.mcp.protocol is mcp.protocol
    assert child._mcp is None


def test_a_child_server_creates_its_root_s():
    root = new_server()
    child = root.create_child_server(prefix="child_")
    mcp = child.mcp
    assert root._mcp is not None
    assert mcp.server is root
    assert mcp.name == root.name

    # Options set through it are the root's
    mcp.max_response_tokens = 5000
    assert root.mcp.max_response_tokens == 5000


def test_exposing_state_creates_it(server):
    child = server.create_child_server(prefix="child_")
    child.state.size = 3
    assert server._mcp is None
    child.state.mcp_expose("size", type=int)
    assert server._mcp is not None
    assert server.mcp._exposes_anything()
    child.state.mcp_unexpose("size")
    assert not server.mcp._exposes_anything()


def test_the_context_is_never_exposed(server):
    with pytest.raises(RuntimeError, match="server-only"):
        server.context.mcp_expose("secret")
    assert server._mcp is None


def test_off_by_default(server):
    mcp = server.mcp

    @mcp.tool
    def ping() -> str:
        """Ping."""
        return "pong"

    server.state.x = 1
    server.state.mcp_expose("x")
    assert mcp.enabled is False
    assert mcp.enabled_locked is False
    assert issubclass(MCPDisabledError, PermissionError)


def test_exposes_anything(server):
    mcp = server.mcp
    assert not mcp._exposes_anything()
    mcp.resource("app://guide")(lambda: "guide")
    assert mcp._exposes_anything()

    mcp = new_server().mcp
    mcp.prompt(lambda: "hi", name="hello")
    assert mcp._exposes_anything()

    mcp = new_server().mcp
    mcp.tool(lambda: "hi", name="hello")
    assert mcp._exposes_anything()


# -----------------------------------------------------------------------------
# Options
# -----------------------------------------------------------------------------


def test_defaults(server):
    mcp = server.mcp
    assert mcp.name == server.name
    assert mcp.enabled is False
    assert mcp.transports == ("http",)
    assert mcp.http.path == "/mcp"
    assert mcp.http.token is None
    assert mcp.http.allowed_origins == ()
    assert mcp.concurrent_calls is False
    assert mcp.structured_content is False
    assert mcp.instructions is None
    assert mcp.max_response_tokens == 8000
    assert dict(mcp.permissions) == {}


def test_configure_sets_options_and_none_leaves_them(server):
    mcp = server.mcp
    mcp.configure(
        name="viewer",
        enabled=True,
        transports=[],
        concurrent_calls=True,
        structured_content=True,
        instructions="A viewer.",
        max_response_tokens=1000,
    )
    assert mcp.name == "viewer"
    assert mcp.enabled is True
    assert mcp.transports == ()
    assert mcp.concurrent_calls is True
    assert mcp.structured_content is True
    assert mcp.instructions == "A viewer."
    assert mcp.max_response_tokens == 1000

    mcp.http.configure(
        path="api/mcp",
        token="s3cret",
        allowed_origins=["https://a.example/", "https://b.example"],
    )
    assert mcp.http.path == "/api/mcp"
    assert mcp.http.token == "s3cret"
    assert mcp.http.allowed_origins == ("https://a.example", "https://b.example")

    # None leaves options unchanged, False is a value
    mcp.configure(name=None, enabled=None)
    mcp.http.configure(token=None)
    assert (mcp.name, mcp.enabled, mcp.http.token) == ("viewer", True, "s3cret")
    mcp.configure(enabled=False)
    mcp.http.configure(token="")
    assert (mcp.enabled, mcp.http.token) == (False, None)

    with pytest.raises(TypeError):
        mcp.configure(bogus=1)
    with pytest.raises(TypeError):
        mcp.configure(token="s3cret")  # the HTTP transport's: mcp.http

    mcp.name = None  # back to the server name
    assert mcp.name == server.name


def test_max_response_tokens(server):
    mcp = server.mcp
    mcp.max_response_tokens = 500
    assert mcp.max_response_tokens == 500
    for bad in (499, 0, -1, "1000", 1000.0, True, None):
        with pytest.raises(
            ValueError, match="max_response_tokens must be an integer of at least 500"
        ):
            mcp.max_response_tokens = bad
    with pytest.raises(ValueError, match="at least 500"):
        mcp.configure(max_response_tokens=100)
    assert mcp.max_response_tokens == 500


def test_allowed_origins_take_one_or_several(server):
    http = server.mcp.http
    http.allowed_origins = "https://a.example/"
    assert http.allowed_origins == ("https://a.example",)
    http.allowed_origins = []
    assert http.allowed_origins == ()


def test_transports(server):
    mcp = server.mcp
    mcp.transports = []  # agents in the process only
    assert mcp.transports == ()
    mcp.transports = "http"
    assert mcp.transports == ("http",)
    mcp.transports = ["http", "http"]
    assert mcp.transports == ("http",)
    for bad in (["stdio"], ["none"], ["http", "HTTP"]):
        with pytest.raises(
            ValueError, match=r"Unknown MCP transport .*available: http"
        ):
            mcp.transports = bad
    assert mcp.transports == ("http",)

    mcp._start()  # it can change while the app runs, as enabled can
    mcp.transports = []
    assert mcp.transports == ()
    assert mcp.transports_locked is False


# -----------------------------------------------------------------------------
# Tools, resources and prompts
# -----------------------------------------------------------------------------


def test_tool_decorator_bare_and_options(mcp):
    @mcp.tool
    def alpha(x: int) -> int:
        """Add one."""
        return x + 1

    @mcp.tool(name="beta_renamed", description="custom")
    def beta() -> str:
        return "ok"

    assert alpha(1) == 2  # the decorator returns the function
    assert [t.name for t in mcp.list_tools()] == ["alpha", "beta_renamed"]
    assert mcp.get_tool("alpha").description == "Add one."
    assert mcp.get_tool("beta_renamed").description == "custom"
    assert mcp.get_tool("beta") is None
    schema = mcp._input_schema(mcp.get_tool("alpha"))
    assert schema["required"] == ["x"]
    assert schema["properties"] == {"x": {"type": "integer"}}


def test_bound_methods_are_tools_resources_and_prompts(mcp):
    class CoreViewer:
        def screenshot(self, width: int = 300) -> str:
            """Capture the view."""
            return f"{width}px"

        def guide(self) -> str:
            """How to use the viewer."""
            return "# Guide"

        def review_session(self, focus: Annotated[str, "What to review"]) -> str:
            return f"Review {focus}"

    viewer = CoreViewer()
    mcp.tool(viewer.screenshot)
    mcp.resource("viewer://guide", mime_type="text/markdown")(viewer.guide)
    mcp.prompt(viewer.review_session)

    tool = mcp.get_tool("screenshot")
    assert tool.description == "Capture the view."
    assert tool.fn() == "300px"
    assert list(mcp._input_schema(tool)["properties"]) == ["width"]

    resource = mcp.get_resource("viewer://guide")
    assert (resource.name, resource.mime_type) == ("guide", "text/markdown")
    assert resource.description == "How to use the viewer."
    assert mcp.list_resources() == [resource]

    prompt = mcp.get_prompt("review_session")
    assert prompt.arguments == [
        {"name": "focus", "required": True, "description": "What to review"}
    ]
    assert mcp.list_prompts() == [prompt]


def test_prompt_keeps_its_description_apart_from_its_arguments(mcp):
    @mcp.prompt(description="Explore a file.")
    def explore(path: Annotated[str, "File to explore"], depth: int = 1) -> str:
        return path * depth

    @mcp.prompt
    def documented(path: Annotated[str, "File to explore"], *args, **kwargs) -> str:  # noqa: ARG001
        """Explore with the docstring."""
        return path

    explore_entry = mcp.get_prompt("explore")
    assert explore_entry.description == "Explore a file."
    assert explore_entry.arguments == [
        {"name": "path", "required": True, "description": "File to explore"},
        {"name": "depth", "required": False},
    ]
    documented_entry = mcp.get_prompt("documented")
    assert documented_entry.description == "Explore with the docstring."
    assert [a["name"] for a in documented_entry.arguments] == ["path"]


def test_tool_annotations(mcp):
    @mcp.tool(read_only=True)
    def look() -> str:
        return "ok"

    @mcp.tool(annotations={"destructiveHint": True})
    def wipe() -> str:
        return "ok"

    @mcp.tool(read_only=True, annotations={"openWorldHint": False})
    def peek() -> str:
        return "ok"

    @mcp.tool
    def plain() -> str:
        return "ok"

    assert mcp.get_tool("look").annotations == {"readOnlyHint": True}
    assert mcp.get_tool("wipe").annotations == {"destructiveHint": True}
    assert mcp.get_tool("peek").annotations == {
        "openWorldHint": False,
        "readOnlyHint": True,
    }
    assert mcp.get_tool("plain").annotations is None
    assert mcp.get_tool("plain").concurrent is False
    assert mcp.get_tool("plain").requires == ()


def test_duplicate_names_raise(mcp):
    @mcp.tool
    def gamma():
        pass

    with pytest.raises(ValueError, match="A tool named 'gamma' is already registered"):

        @mcp.tool(name="gamma")
        def other():
            pass

    def info():
        return {}

    mcp.resource("app://info")(info)
    with pytest.raises(ValueError, match="'app://info' is already registered"):
        mcp.resource("app://info")(info)

    mcp.prompt(lambda: "", name="intro")
    with pytest.raises(
        ValueError, match="A prompt named 'intro' is already registered"
    ):
        mcp.prompt(lambda: "", name="intro")


RESERVED = (
    "object_list",
    "object_types",
    "object_get",
    "object_update",
    "object_call",
    "object_batch",
)


def test_the_reserved_names_are_the_object_tools():
    assert set(OBJECT_TOOLS) == set(RESERVED)


@pytest.mark.parametrize("name", RESERVED)
def test_the_object_tool_names_are_reserved(mcp, name):
    def fn():
        pass

    with pytest.raises(ValueError, match="is the name of a built-in object tool"):
        mcp.tool(fn, name=name)
    fn.__name__ = name
    with pytest.raises(ValueError, match="is the name of a built-in object tool"):
        mcp.tool(fn)

    # also once the object tools are there
    mcp.server.state.size = 1
    mcp.server.state.mcp_expose("size")
    entry = mcp.get_tool(name)
    with pytest.raises(ValueError, match="is the name of a built-in object tool"):
        mcp.tool(fn)
    assert mcp.get_tool(name) is entry


def test_tool_names_use_the_characters_clients_accept(mcp, caplog):
    def fn():
        pass

    for bad in ("has space", "émoji", "a/b", 3):
        with pytest.raises(ValueError, match="A tool name is 1-128 of"):
            mcp.tool(fn, name=bad)
    mcp.tool(fn, name="with-dash_and_underscore")

    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        mcp.tool(fn, name="with.dot")
    assert "OpenAI-style function calling rejects dots in names" in caplog.text
    assert mcp.get_tool("with.dot") is not None


def test_a_full_tool_name_over_64_characters_raises(mcp):
    def fn():
        pass

    mcp.name = "app"  # mcp__app__<tool>: 10 characters before the tool name
    mcp.tool(fn, name="a" * 54)
    with pytest.raises(ValueError, match="has 65 characters") as error:
        mcp.tool(fn, name="b" * 55)
    assert str(error.value) == (
        f"Tool '{'b' * 55}': its full name 'mcp__app__{'b' * 55}' has 65 characters; "
        "clients such as Claude Code reject more than 64. Shorten the tool name "
        "or mcp.name"
    )
    assert mcp.get_tool("b" * 55) is None

    # the default name is the trame server's, which counts too
    mcp = new_server().mcp
    room = 64 - len(f"mcp__{mcp.name}__")
    mcp.tool(fn, name="c" * room)
    with pytest.raises(ValueError, match="has 65 characters"):
        mcp.tool(fn, name="d" * (room + 1))


def test_a_longer_name_set_later_is_checked_at_start(mcp, caplog):
    @mcp.tool
    def reset():
        pass

    mcp.name = "n" * 60
    with pytest.raises(ValueError, match=r"Shorten the tool name or mcp\.name"):
        mcp.tool(lambda: None, name="other")

    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        mcp._start()
    assert (
        f"Tool 'reset': its full name 'mcp__{'n' * 60}__reset' has 72 characters"
        in caplog.text
    )
    assert mcp.get_tool("reset") is not None  # warned, still served


# -----------------------------------------------------------------------------
# Launch options (Server.cli)
# -----------------------------------------------------------------------------


def test_the_launch_flags_are_part_of_the_server_cli(server):
    cli = server.cli
    args, unknown = cli.parse_known_args(
        [
            "--mcp",
            "--mcp-transport",
            "http",
            "--mcp-http-token",
            "t0k",
            "--mcp-log",
            "--mcp-deny",
            "files,net",
            "--mcp-deny",
            "scripts",
            "--app-option",
        ]
    )
    assert args.mcp is True
    assert args.mcp_transport == ("http",)
    assert args.mcp_http_token == "t0k"
    assert args.mcp_log is True
    assert args.mcp_deny == ["files,net", "scripts"]
    assert unknown == ["--app-option"]  # harmless to apps that don't use MCP

    args, _ = cli.parse_known_args([])
    assert (
        args.mcp,
        args.mcp_transport,
        args.mcp_http_token,
        args.mcp_log,
        args.mcp_deny,
    ) == (None, None, None, False, None)
    assert cli.parse_known_args(["--no-mcp"])[0].mcp is False


def test_the_transport_flag(server, capsys):
    cli = server.cli

    def transports(*argv):
        return cli.parse_known_args(list(argv))[0].mcp_transport

    # comma-separated and repeatable, like --mcp-deny
    assert transports("--mcp-transport", "none") == ("none",)
    assert transports("--mcp-transport", "http,http") == ("http",)
    assert transports("--mcp-transport", "http", "--mcp-transport", "http") == ("http",)
    assert transports("--mcp-transport=http") == ("http",)
    assert transports("--no-mcp-transport", "--mcp-transport", "none") == ("none",)

    assert cli.parse_known_args(["--no-mcp-transport"])[0].mcp_no_transport is True
    assert cli.parse_known_args([])[0].mcp_no_transport is False

    # wrong values fail as they are parsed, like any other wrong value
    for argv, error in [
        (
            ["--no-mcp-transport", "--mcp-transport", "http"],
            "--no-mcp-transport serves none",
        ),
        (
            ["--mcp-transport", "http", "--no-mcp-transport"],
            "--mcp-transport names a transport",
        ),
        (["--mcp-transport", "stdoi"], "unknown transport 'stdoi' (choose from http"),
        (["--mcp-transport", "none,http"], "none can't be combined with a transport"),
        (["--mcp-transport", "http", "--mcp-transport", "none"], "can't be combined"),
    ]:
        with pytest.raises(SystemExit):
            cli.parse_known_args(argv)
        assert error in capsys.readouterr().err


def test_launch_options_win_until_start(monkeypatch):
    # trame reads TRAME_ARGS instead of sys.argv when running under pytest
    monkeypatch.setenv("TRAME_ARGS", "--no-mcp --mcp-http-token from-cli")
    mcp = new_server().mcp
    mcp.configure(enabled=True, transports=["http"])
    mcp.http.configure(token="from-code")
    assert mcp.enabled is False
    assert mcp.enabled_locked is True
    assert mcp.transports == ()  # --no-mcp: nothing served
    assert mcp.http.token == "from-cli"

    # the application's values are only defaults before start, however set
    mcp.enabled = True
    mcp.http.token = "from-attribute"
    assert mcp.enabled is False
    assert mcp.http.token == "from-cli"

    # once started every assignment applies, except what --no-mcp withholds
    mcp._start()
    mcp.http.token = "after-start"
    assert mcp.http.token == "after-start"
    mcp.enabled = True
    assert mcp.enabled is False


def test_the_transports_from_the_command_line(monkeypatch):
    monkeypatch.setenv("TRAME_ARGS", "--mcp-transport none")
    mcp = new_server().mcp
    assert mcp.transports == ()
    assert mcp.enabled is False  # choosing transports doesn't turn access on
    mcp.transports = ["http"]  # the launch value wins until start
    assert mcp.transports == ()

    # only a starting value: once running, the app may open a transport
    mcp._start()
    mcp.transports = ["http"]
    assert mcp.transports == ("http",)

    monkeypatch.setenv("TRAME_ARGS", "--mcp --mcp-transport http")
    mcp = new_server().mcp
    mcp.transports = []
    assert (mcp.enabled, mcp.transports) == (True, ("http",))


@pytest.mark.parametrize("flags", ["--no-mcp-transport", "--no-mcp"])
def test_no_transport_for_the_whole_run(monkeypatch, flags):
    monkeypatch.setenv("TRAME_ARGS", flags)
    mcp = new_server().mcp
    assert mcp.transports == ()
    assert mcp.transports_locked is True
    mcp.transports = ["http"]
    mcp._start()
    mcp.transports = ["http"]  # held for the run
    assert mcp.transports == ()
    mcp.transports = []  # withholding more is fine
    if flags == "--no-mcp-transport":
        mcp.enabled = True  # agents in the process are still allowed
        assert mcp.enabled is True


def test_only_withholding_launch_options_hold_after_start(monkeypatch):
    monkeypatch.setenv("TRAME_ARGS", "--mcp")
    mcp = new_server().mcp
    assert mcp.enabled is True
    assert mcp.enabled_locked is False
    mcp.enabled = False  # before start, the launch value wins
    assert mcp.enabled is True
    mcp._start()
    mcp.enabled = False  # turning on only set the starting value
    assert mcp.enabled is False

    monkeypatch.setenv("TRAME_ARGS", "--no-mcp")
    mcp = new_server().mcp
    assert mcp.enabled_locked is True
    mcp._start()
    mcp.enabled = True  # turning off holds for the run
    assert mcp.enabled is False


def test_the_token_from_the_environment(monkeypatch):
    monkeypatch.setenv("TRAME_MCP_HTTP_TOKEN", "from-env")
    mcp = new_server().mcp
    assert mcp.http.token == "from-env"
    mcp.http.token = "from-code"
    assert mcp.http.token == "from-env"

    # the command line comes first
    monkeypatch.setenv("TRAME_ARGS", "--mcp-http-token from-cli")
    assert new_server().mcp.http.token == "from-cli"


def test_launch_options_are_read_when_it_is_created(monkeypatch):
    """Server.cli is the server's; the MCP reads it when first accessed."""
    server = new_server()
    assert server.cli is server.cli
    monkeypatch.setenv("TRAME_ARGS", "--mcp")
    assert server.mcp.enabled is True


# -----------------------------------------------------------------------------
# A running server
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_at_launch_turns_access_on(monkeypatch, capsys, caplog):
    monkeypatch.setenv("TRAME_ARGS", "--mcp")
    server = new_server()
    server.mcp.tool(lambda: "pong", name="ping")
    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        await start(server)
    try:
        assert server.mcp.enabled is True
        assert capsys.readouterr().out.count("MCP server available") == 1
        assert "exposes nothing" not in caplog.text
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                server.mcp.http.url,
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            ) as response,
        ):
            assert response.status == 200
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("create", [False, True])
async def test_mcp_at_launch_with_nothing_exposed_warns(monkeypatch, caplog, create):
    monkeypatch.setenv("TRAME_ARGS", "--mcp")
    server = new_server()
    if create:
        server.mcp  # noqa: B018
    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        await start(server)
    try:
        assert "--mcp is given, but this app exposes nothing to agents" in caplog.text
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_the_url_names_the_bound_host():
    server = new_server()
    mcp = server.mcp
    await start(server, host="127.0.0.1")
    try:
        assert mcp.http.url == f"http://127.0.0.1:{server.port}/mcp"
        assert mcp.http.token is None  # loopback: no token needed
    finally:
        await server.stop()
