"""The launch options of agent access (``trame_server.mcp.cli``): the flags,
the environment, and what they choose. No server is needed."""

import argparse

import pytest

from trame_server.mcp import cli
from trame_server.mcp.cli import (
    DENY_ENV,
    HTTP_TOKEN_ENV,
    LOG_ENV,
    LaunchOptions,
    launch_names,
    to_launch_options,
)
from trame_server.mcp.core import TRANSPORTS


def new_parser(transports=TRANSPORTS):
    parser = argparse.ArgumentParser()
    cli.add_arguments(parser, transports)
    return parser


def parse(*argv):
    return new_parser().parse_known_args(list(argv))[0]


def test_the_transport_flag(capsys):
    def transports(*argv):
        return parse(*argv).mcp_transport

    # comma-separated and repeatable, like --mcp-deny
    assert transports("--mcp-transport", "none") == ("none",)
    assert transports("--mcp-transport", "http,http") == ("http",)
    assert transports("--mcp-transport", "http", "--mcp-transport", "http") == ("http",)
    assert transports("--mcp-transport=http") == ("http",)
    assert transports("--no-mcp-transport", "--mcp-transport", "none") == ("none",)

    assert parse("--no-mcp-transport").mcp_no_transport is True
    assert parse().mcp_no_transport is False

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
            new_parser().parse_known_args(argv)
        assert error in capsys.readouterr().err


def test_the_caller_names_the_transports(capsys):
    parser = new_parser(("http", "stdio"))
    args = parser.parse_known_args(["--mcp-transport", "stdio,http"])[0]
    assert args.mcp_transport == ("stdio", "http")

    with pytest.raises(SystemExit):
        parser.parse_known_args(["--mcp-transport", "ws"])
    assert "(choose from http, stdio, or none)" in capsys.readouterr().err

    help_text = " ".join(parser.format_help().split())
    assert "http, stdio, or none" in help_text


def test_nothing_given_leaves_every_choice_to_the_application():
    assert to_launch_options(None, {}) == LaunchOptions()
    assert to_launch_options(parse(), {}) == LaunchOptions()
    assert LaunchOptions() == LaunchOptions(
        enabled=None,
        transports=None,
        transports_withheld=False,
        token=None,
        log=False,
        denied=(),
    )


def test_the_flags():
    args = parse(
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
    )
    assert to_launch_options(args, {}) == LaunchOptions(
        enabled=True,
        transports=("http",),
        token="t0k",
        log=True,
        denied=("files", "net", "scripts"),
    )


def test_withholding_transports():
    # --no-mcp withholds the transports too
    assert to_launch_options(parse("--no-mcp"), {}) == LaunchOptions(
        enabled=False, transports=(), transports_withheld=True
    )
    assert to_launch_options(parse("--no-mcp-transport"), {}) == LaunchOptions(
        transports=(), transports_withheld=True
    )
    # none chooses no transport at start, which the application may change
    assert to_launch_options(parse("--mcp-transport", "none"), {}) == LaunchOptions(
        transports=()
    )


def test_the_environment():
    environ = {HTTP_TOKEN_ENV: "from-env", LOG_ENV: "1", DENY_ENV: "net, cloud"}
    assert to_launch_options(parse(), environ) == LaunchOptions(
        token="from-env", log=True, denied=("net", "cloud")
    )

    # the token flag wins, while both the flag and the variable deny
    options = to_launch_options(
        parse("--mcp-http-token", "from-cli", "--mcp-deny", "files"), environ
    )
    assert options.token == "from-cli"
    assert options.denied == ("files", "net", "cloud")

    # empty variables are not given
    environ = {HTTP_TOKEN_ENV: "", LOG_ENV: "", DENY_ENV: ""}
    assert to_launch_options(parse(), environ) == LaunchOptions()


def test_the_environment_defaults_to_the_process_one(monkeypatch):
    monkeypatch.setenv(HTTP_TOKEN_ENV, "from-env")
    monkeypatch.delenv(LOG_ENV, raising=False)
    monkeypatch.delenv(DENY_ENV, raising=False)
    assert to_launch_options(None) == LaunchOptions(token="from-env")


def test_launch_names():
    assert launch_names(["a, b", None, "", " c ", ",,d"]) == ("a", "b", "c", "d")
    assert launch_names([]) == ()
