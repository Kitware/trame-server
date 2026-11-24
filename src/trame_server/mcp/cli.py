"""The launch options of agent access: the flags ``Server.cli`` accepts
(``--mcp``, ``--mcp-transport``, ...) and the environment variables that go
with some of them.

:func:`add_arguments` adds the flags to an argparse parser, and
:func:`to_launch_options` reads the parsed arguments and the environment
into :class:`LaunchOptions`, which ``server.mcp`` applies (see
:class:`trame_server.mcp.core.MCP`). This module doesn't know which
transports exist: the caller passes them to :func:`add_arguments`.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass

__all__ = [
    "DENY_ENV",
    "HTTP_TOKEN_ENV",
    "LOG_ENV",
    "LaunchOptions",
    "add_arguments",
    "to_launch_options",
]

HTTP_TOKEN_ENV = "TRAME_MCP_HTTP_TOKEN"
LOG_ENV = "TRAME_MCP_LOG"
DENY_ENV = "TRAME_MCP_DENY"


@dataclass(frozen=True)
class LaunchOptions:
    """What the person running the application chose at launch. None leaves the
    choice to the application."""

    #: ``--mcp`` (True) or ``--no-mcp`` (False)
    enabled: bool | None = None
    #: The names given to ``--mcp-transport``, empty for ``none``, and also
    #: empty with ``--no-mcp-transport`` or ``--no-mcp``
    transports: tuple[str, ...] | None = None
    #: ``--no-mcp-transport`` or ``--no-mcp``: no transport for the whole run
    transports_withheld: bool = False
    #: ``--mcp-http-token``, else ``TRAME_MCP_HTTP_TOKEN``
    token: str | None = None
    #: ``--mcp-log`` or ``TRAME_MCP_LOG``
    log: bool = False
    #: The permissions ``--mcp-deny`` and ``TRAME_MCP_DENY`` deny for the
    #: whole run. Both apply, since each withholds something
    denied: tuple[str, ...] = ()


def to_launch_options(args, environ: Mapping[str, str] | None = None) -> LaunchOptions:
    """The launch options in ``args``, as parsed by a parser that
    :func:`add_arguments` set up, and in ``environ`` (default ``os.environ``).
    A flag missing from ``args``, or ``args`` None, counts as not given."""
    if environ is None:
        environ = os.environ
    enabled = getattr(args, "mcp", None)
    withheld = enabled is False or bool(getattr(args, "mcp_no_transport", False))
    transports = getattr(args, "mcp_transport", None)
    if withheld or transports == ("none",):
        transports = ()
    return LaunchOptions(
        enabled=enabled,
        transports=transports,
        transports_withheld=withheld,
        token=getattr(args, "mcp_http_token", None)
        or environ.get(HTTP_TOKEN_ENV)
        or None,
        log=bool(getattr(args, "mcp_log", False) or environ.get(LOG_ENV)),
        denied=launch_names(
            [*(getattr(args, "mcp_deny", None) or ()), environ.get(DENY_ENV)]
        ),
    )


def launch_names(values) -> tuple[str, ...]:
    """Names given at launch, each value comma-separated."""
    return tuple(n.strip() for v in values if v for n in v.split(",") if n.strip())


def add_arguments(parser, transports: Collection[str]):
    """Add the launch options of agent access (``--mcp``, ``--mcp-transport``,
    ...) to an argparse ``parser``. ``transports`` are the names
    ``--mcp-transport`` accepts, besides ``none``."""
    parser.add_argument(
        "--mcp",
        dest="mcp",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="""Turn agent access through MCP on or off. --no-mcp holds for the
                whole run: no transport is served and agents in the process
                are refused too.""",
    )
    parser.add_argument(
        "--mcp-transport",
        dest="mcp_transport",
        action=_MCPTransports,
        transports=transports,
        metavar="TRANSPORT",
        default=None,
        help=f"""How agents outside the process connect at start, instead of
                the application's choice: {", ".join(transports)}, or none for
                agents in the process only. Comma-separated, repeatable. The
                application may change it once running.""",
    )
    parser.add_argument(
        "--no-mcp-transport",
        dest="mcp_no_transport",
        action=_NoMCPTransport,
        default=False,
        help="""Serve no transport for the whole run, so that only agents in
                the process can connect, when access is on.""",
    )
    parser.add_argument(
        "--mcp-http-token",
        dest="mcp_http_token",
        metavar="TOKEN",
        help=f"Bearer token required on the HTTP transport (or set {HTTP_TOKEN_ENV})",
    )
    parser.add_argument(
        "--mcp-log",
        dest="mcp_log",
        action="store_true",
        help=f"""Log what agents call, at INFO on the trame_server.mcp loggers
                (or set {LOG_ENV})""",
    )
    parser.add_argument(
        "--mcp-deny",
        dest="mcp_deny",
        action="append",
        metavar="PERMISSION",
        default=None,
        help=f"""Deny agents these permissions for the whole run: the application
                cannot allow them again. Comma-separated, repeatable (or set
                {DENY_ENV})""",
    )


class _MCPTransports(argparse.Action):
    """Parse ``--mcp-transport``, which is comma-separated and repeatable. Each name
    is checked against ``transports`` as it is parsed, so that a wrong one fails
    like any other wrong value."""

    def __init__(self, option_strings, dest, transports=(), **kwargs):
        super().__init__(option_strings, dest, **kwargs)
        self.transports = transports

    def __call__(self, parser, namespace, values, option_string=None):
        names = [*(getattr(namespace, self.dest, None) or ())]
        names += [n.strip() for n in values.split(",") if n.strip()]
        unknown = [n for n in names if n not in (*self.transports, "none")]
        if unknown:
            parser.error(
                f"{option_string}: unknown transport {unknown[0]!r} "
                f"(choose from {', '.join(self.transports)}, or none)"
            )
        if "none" in names and len(set(names)) > 1:
            parser.error(f"{option_string}: none can't be combined with a transport")
        if getattr(namespace, "mcp_no_transport", False) and names != ["none"]:
            parser.error(f"{option_string}: --no-mcp-transport serves none")
        setattr(namespace, self.dest, tuple(dict.fromkeys(names)))


class _NoMCPTransport(argparse.Action):
    """Parse ``--no-mcp-transport``, which contradicts a ``--mcp-transport`` that
    names a transport, whichever comes first."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, _values, option_string=None):
        if (getattr(namespace, "mcp_transport", None) or ("none",)) != ("none",):
            parser.error(f"{option_string}: --mcp-transport names a transport")
        setattr(namespace, self.dest, True)
