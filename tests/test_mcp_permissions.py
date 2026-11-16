"""Permissions (``mcp.permissions``, ``requires=``, ``--mcp-deny``): powers
the people running an application withhold from agents."""

import itertools
import logging

import pytest
from trame.app import get_server

from trame_server.mcp import PermissionDeniedError
from trame_server.mcp.permissions import Permissions, launch_names

_counter = itertools.count()

LAUNCH_VARIABLES = (
    "TRAME_ARGS",
    "TRAME_MCP_HTTP_TOKEN",
    "TRAME_MCP_LOG",
    "TRAME_MCP_DENY",
)


def rpc(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def off(name, description):
    return (
        f'{name}: permission "{description[0]}" ({description[1]}) is off; '
        f"only the people running the app can turn it on."
    )


@pytest.fixture(autouse=True)
def _no_launch_options(monkeypatch):
    for name in LAUNCH_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mcp():
    mcp = get_server(f"test_mcp_permissions_{next(_counter)}").mcp
    mcp.enabled = True
    return mcp


@pytest.fixture
def permissions(mcp):
    mcp.permissions.declare("files", "Read files and folders")
    mcp.permissions.declare("scripts", "Run code the agent writes", requires="files")
    return mcp.permissions


# -----------------------------------------------------------------------------
# Declaring and setting
# -----------------------------------------------------------------------------


def test_a_permission_is_allowed_only_with_what_it_requires(permissions):
    assert dict(permissions) == {"files": True, "scripts": True}
    permissions["files"] = False  # a script could read files anyway
    assert permissions.denied == ("files", "scripts")
    refused = r"denied permission \('scripts' requires 'files'\); allow them"
    with pytest.raises(ValueError, match=refused):
        permissions["scripts"] = True  # never brings files back by itself
    assert permissions.denied == ("files", "scripts")
    permissions.update(files=True, scripts=True)
    assert permissions.denied == ()
    permissions["scripts"] = False
    assert permissions.denied == ("scripts",)

    with pytest.raises(ValueError, match=refused):
        permissions.update(scripts=True, files=False)
    assert permissions.denied == ("scripts",)  # all or none
    with pytest.raises(KeyError, match="No permission 'script' is declared"):
        permissions["script"] = False
    with pytest.raises(KeyError, match="No permission 'script' is declared"):
        permissions["script"]

    permissions.update({"scripts": True}, files=True)
    assert permissions.denied == ()


def test_declarations_are_checked(mcp):
    permissions = mcp.permissions
    with pytest.raises(ValueError, match="not declared"):
        permissions.declare("scripts", "Run code", requires="files")
    permissions.declare("files", "Read files", allowed=False)
    permissions.declare("scripts", "Run code", requires=["files"])
    assert permissions["scripts"] is False  # never allowed without what it requires
    with pytest.raises(ValueError, match="already declared"):
        permissions.declare("files", "Read files")
    with pytest.raises(TypeError, match="non-empty string"):
        permissions.declare("", "Nothing")
    with pytest.raises(TypeError, match="requires must be a permission name"):
        permissions.declare("net", "Network", requires=3)

    def ping() -> str:
        return "pong"

    with pytest.raises(TypeError, match="requires must be a permission name"):
        mcp.tool(requires=3)(ping)
    with pytest.raises(TypeError, match="requires must be a permission name"):
        mcp.tool(ping, requires=[""])
    assert mcp.get_tool("ping") is None


def test_what_is_missing_is_named_through_the_chain():
    permissions = Permissions()
    permissions.declare("net", "Use the network", allowed=False)
    permissions.declare("cloud", "Use the cloud", requires="net")
    permissions.declare("backup", "Back up to the cloud", requires="cloud")
    with pytest.raises(ValueError, match="'backup' requires 'net', 'cloud'"):
        permissions["backup"] = True
    permissions.update(net=True, cloud=True, backup=True)
    assert permissions.denied == ()
    permissions["net"] = False
    assert permissions.denied == ("net", "cloud", "backup")


def test_a_mapping_of_what_is_allowed():
    permissions = Permissions()
    assert len(permissions) == 0
    permissions.declare("files", "Read files")
    permissions.declare("net", "Use the network", allowed=False)
    assert list(permissions) == ["files", "net"]
    assert repr(permissions) == "Permissions({'files': True, 'net': False})"
    assert permissions.description("net") == "Use the network"
    assert permissions.allows([])
    assert permissions.allows(["files"])
    assert not permissions.allows(["files", "net"])
    assert not permissions.allows(["undeclared"])


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_tool_is_not_offered_and_refused(mcp, permissions):
    @mcp.tool(requires="files")
    def list_files(path: str) -> list:
        return [path]

    @mcp.tool
    def ping() -> str:
        return "pong"

    permissions["files"] = False
    listed = await mcp.protocol.handle(rpc("tools/list"))
    assert [t["name"] for t in listed["result"]["tools"]] == ["ping"]
    assert mcp.list_tools() == [mcp.get_tool("ping")]

    # A client that listed it earlier still calls it
    reply = await mcp.protocol.handle(
        rpc("tools/call", {"name": "list_files", "arguments": {"path": "/"}})
    )
    assert reply["result"]["isError"]
    assert reply["result"]["content"][0]["text"] == off(
        "list_files", ("files", "Read files and folders")
    )

    permissions["files"] = True
    assert await mcp.protocol._execute(mcp.get_tool("list_files"), {"path": "/"}) == [
        "/"
    ]


@pytest.mark.asyncio
async def test_a_tool_needing_several_permissions(mcp, permissions):
    permissions.declare("net", "Use the network")

    @mcp.tool(requires=["files", "net"])
    def upload(path: str) -> str:
        return path

    assert mcp.get_tool("upload").requires == ("files", "net")
    permissions["net"] = False
    assert mcp.list_tools() == []
    with pytest.raises(PermissionDeniedError) as refused:
        await mcp.protocol._execute(mcp.get_tool("upload"), {"path": "/"})
    assert str(refused.value) == off("upload", ("net", "Use the network"))


@pytest.mark.asyncio
async def test_a_call_checks_what_its_arguments_need(mcp, permissions):
    @mcp.tool
    def run(external: bool = False) -> str:
        if external:
            mcp.permissions.require("files", what="run(external)")
        return "ran"

    permissions["files"] = False
    assert await mcp.protocol._execute(mcp.get_tool("run"), {}) == "ran"
    with pytest.raises(PermissionDeniedError) as refused:
        await mcp.protocol._execute(mcp.get_tool("run"), {"external": True})
    assert str(refused.value) == off(
        "run(external)", ("files", "Read files and folders")
    )

    # The agent reads the message as is, without the exception's type
    reply = await mcp.protocol.handle(
        rpc("tools/call", {"name": "run", "arguments": {"external": True}})
    )
    assert reply["result"]["content"][0]["text"] == str(refused.value)


def test_require_names_the_refused_action(permissions):
    permissions.require()  # nothing needed
    permissions.require("files", "scripts")
    permissions["scripts"] = False
    with pytest.raises(
        PermissionDeniedError, match=r'^This call: permission "scripts"'
    ):
        permissions.require("files", "scripts")
    with pytest.raises(
        PermissionDeniedError,
        match=r'^Export: permission "printer" was never declared by the app$',
    ):
        permissions.require("printer", what="Export")


@pytest.mark.asyncio
async def test_a_tool_needing_an_undeclared_permission_is_never_offered(mcp, caplog):
    @mcp.tool(requires="network")
    def fetch() -> str:
        return "fetched"

    assert mcp.list_tools() == []
    with caplog.at_level(logging.WARNING, logger="trame_server.mcp"):
        mcp._start()
    assert (
        "Tool fetch requires undeclared permissions ['network']; it is never offered"
        in caplog.text
    )
    reply = await mcp.protocol.handle(rpc("tools/call", {"name": "fetch"}))
    assert reply["result"]["isError"]
    assert reply["result"]["content"][0]["text"] == (
        'fetch: permission "network" was never declared by the app'
    )


@pytest.mark.asyncio
async def test_the_instructions_say_what_is_turned_off(mcp, permissions):
    async def instructions():
        reply = await mcp.protocol.handle(rpc("initialize"))
        return reply["result"]["instructions"]

    assert "Turned off" not in await instructions()
    permissions["scripts"] = False
    assert (
        "Turned off in this application: scripts (Run code the agent writes). What "
        "needs them is not offered, and calls to it are refused."
    ) in await instructions()


# -----------------------------------------------------------------------------
# Launch
# -----------------------------------------------------------------------------


def _launched(monkeypatch, argv, env=None):
    # trame reads TRAME_ARGS instead of sys.argv when running under pytest
    monkeypatch.setenv("TRAME_ARGS", argv)
    if env is not None:
        monkeypatch.setenv("TRAME_MCP_DENY", env)
    mcp = get_server(f"test_mcp_permissions_launch_{next(_counter)}").mcp
    mcp.enabled = True
    mcp.permissions.declare("files", "Read files")
    mcp.permissions.declare("scripts", "Run code", requires="files")
    return mcp


def test_launch_names():
    assert launch_names(["a, b", None, "", " c ", ",,d"]) == ("a", "b", "c", "d")
    assert launch_names([]) == ()


def test_the_command_line_denies_for_the_whole_run(monkeypatch):
    mcp = _launched(monkeypatch, "--mcp-deny files")
    permissions = mcp.permissions
    assert permissions.denied == permissions.locked == ("files", "scripts")
    permissions["scripts"] = True
    assert permissions.denied == ("files", "scripts")
    mcp._start()
    permissions.update(files=True, scripts=True)  # a UI switch, once running
    assert permissions.denied == ("files", "scripts")

    # Denying scripts leaves files to the application
    mcp = _launched(monkeypatch, "--mcp-deny scripts")
    permissions = mcp.permissions
    assert permissions.locked == ("scripts",)
    mcp._start()
    permissions["files"] = False
    permissions["scripts"] = True  # locked: nothing changes
    assert permissions.denied == ("files", "scripts")
    permissions["files"] = True
    assert permissions.denied == ("scripts",)


def test_a_permission_declared_later_is_denied_too(monkeypatch):
    mcp = _launched(monkeypatch, "--mcp-deny net")
    mcp.permissions.declare("net", "Use the network")
    mcp.permissions.declare("cloud", "Use the cloud", requires="net")
    assert mcp.permissions.denied == ("net", "cloud")
    assert mcp.permissions.locked == ("net", "cloud")


def test_the_environment_denies_too(monkeypatch):
    mcp = _launched(
        monkeypatch, "--mcp-deny files --mcp-deny net,cloud", env="scripts, "
    )
    assert mcp.permissions._launch_denied == {"files", "net", "cloud", "scripts"}


@pytest.mark.asyncio
async def test_an_unknown_name_at_launch_refuses_every_call(monkeypatch, caplog):
    mcp = _launched(monkeypatch, "--mcp-deny script")

    @mcp.tool
    def ping() -> str:
        return "pong"

    # Until the server starts, the application may still declare it
    assert await mcp.protocol._execute(mcp.get_tool("ping"), {}) == "pong"

    with caplog.at_level(logging.ERROR, logger="trame_server.mcp"):
        mcp._start()
    assert (
        "--mcp-deny names script, which this application does not declare "
        "(it declares: files, scripts); every agent call is refused"
    ) in caplog.text
    with pytest.raises(PermissionDeniedError, match="launched denying script"):
        await mcp.protocol._execute(mcp.get_tool("ping"), {})
    reply = await mcp.protocol.handle(rpc("tools/call", {"name": "ping"}))
    assert reply["result"]["content"][0]["text"] == (
        "Agent access is refused: the application was launched denying script, "
        "which it does not declare"
    )
