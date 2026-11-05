"""Permissions: capabilities that the people running an application can
withhold from agents (``mcp.permissions``, ``--mcp-deny``).

The application declares each capability it controls, and names the
permissions that a tool, a method, a property or a constructor needs with
``requires=``:

.. code-block:: python

    server.mcp.permissions.declare("files", "Read files and folders on this computer")
    server.mcp.permissions.declare(
        "scripts", "Run Python code the agent writes", requires="files"
    )


    @mcp.method(requires="files")
    def list_files(self, path: str) -> dict: ...

While a permission is denied, what needs it is left out of what agents are
offered (``tools/list``, ``object_types``), and calls to it are refused
with :class:`PermissionDeniedError`. A client that listed the tools
earlier still has them, and nothing tells it the list changed.
``require()`` checks inside a call, for a need that depends on the
arguments.

``requires`` on a permission means what it means on a tool: the
permission is allowed only while the ones it requires are, typically
because it grants them anyway (a script can read files). Allowing it while
one of them stays denied raises, and denying one denies the ones requiring
it, so no setting holds one without the other.

``--mcp-deny NAME[,NAME]`` (repeatable) and ``TRAME_MCP_DENY`` deny
permissions for the whole run. Whoever launched the application decided,
and neither its code nor its UI can allow them again (``locked`` tells a
UI which switches to disable). A name the application does not declare
refuses every agent call once the server runs: the user meant to withhold
something, and a typo must not leave it allowed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from trame_common.obj.mcp import permission_names

logger = logging.getLogger("trame_server.mcp")

__all__ = ["DENY_ENV", "PermissionDeniedError", "Permissions"]

DENY_ENV = "TRAME_MCP_DENY"


class PermissionDeniedError(PermissionError):
    """A call needs a permission that is denied (``mcp.permissions``)."""


def launch_names(values) -> tuple[str, ...]:
    """Names given at launch, each value comma-separated."""
    return tuple(n.strip() for v in values if v for n in v.split(",") if n.strip())


@dataclass
class _Permission:
    description: str
    requires: tuple[str, ...]
    allowed: bool


class Permissions(Mapping):
    """The declared permissions (``mcp.permissions``), as a mapping from each
    name to whether agents are allowed it. Assign ``permissions[name] =
    bool``, or call :meth:`update` to set several at once, at any time."""

    def __init__(self):
        self._declared: dict[str, _Permission] = {}
        self._launch_denied = frozenset()
        self._started = False

    def __getitem__(self, name) -> bool:
        return self._get(name).allowed

    def __iter__(self):
        return iter(self._declared)

    def __len__(self):
        return len(self._declared)

    def __setitem__(self, name, allowed):
        self.update({name: allowed})

    def __repr__(self):
        return f"Permissions({dict(self)!r})"

    def declare(self, name, description, *, requires=None, allowed=True):
        """Declare a permission, allowed unless ``allowed=False``.

        :param description: what it lets an agent do, in a few words. An agent
            reads it when a call is refused.
        :param requires: the permissions, declared earlier, that must be allowed
            for this one to be, such as those it grants anyway. It starts denied
            when one of them is denied.
        """
        if not isinstance(name, str) or not name:
            msg = f"A permission name is a non-empty string, got {name!r}"
            raise TypeError(msg)
        if name in self._declared:
            msg = f"The permission {name!r} is already declared"
            raise ValueError(msg)
        requires = permission_names(requires)
        unknown = [n for n in requires if n not in self._declared]
        if unknown:
            msg = f"{name!r} requires {unknown}, which are not declared (declare them first)"
            raise ValueError(msg)
        allowed = (
            bool(allowed)
            and name not in self._launch_denied
            and all(self._declared[n].allowed for n in requires)
        )
        self._declared[name] = _Permission(str(description), requires, allowed)

    def update(self, values=(), /, **kwargs):
        """Allow (True) or deny (False) several permissions at once, all or
        none.

        A permission is allowed only with those it requires: allowing one
        while one of them stays denied raises ``ValueError``, so allow both
        in the same call. Denying one also denies those requiring it. A
        permission denied at launch (``locked``) stays denied.
        """
        changes = {**dict(values), **kwargs}
        for name in changes:
            self._get(name)
        deny = self._closure({n for n, v in changes.items() if not v}, self._requiring)
        # Locked ones are left out (what requires a locked one is locked too)
        allowing = {n for n, v in changes.items() if v}
        held = allowing & set(self.locked)
        allowed = allowing - held

        def ends_allowed(name):
            return name in allowed or (
                self._declared[name].allowed and name not in deny
            )

        missing = {}
        for name in self._ordered(allowed):
            needed = self._closure(self._declared[name].requires, self._required)
            needed = [r for r in self._ordered(needed) if not ends_allowed(r)]
            if needed:
                missing[name] = needed
        if missing:
            needs = "; ".join(
                f"{name!r} requires {', '.join(map(repr, needed))}"
                for name, needed in missing.items()
            )
            msg = (
                f"Cannot allow what requires a denied permission ({needs}); allow "
                f"them in the same update"
            )
            raise ValueError(msg)
        if held:
            logger.info(
                "Not allowing %s: denied at launch for this run",
                ", ".join(sorted(held)),
            )
        for name in allowed:
            self._declared[name].allowed = True
        for name in deny:
            self._declared[name].allowed = False

    @property
    def locked(self) -> tuple[str, ...]:
        """The permissions denied at launch, and those requiring them:
        denied for the whole run, whatever is assigned."""
        held = self._closure(
            self._launch_denied & self._declared.keys(), self._requiring
        )
        return self._ordered(held)

    @property
    def denied(self) -> tuple[str, ...]:
        """The names of the denied permissions, in declaration order."""
        return tuple(name for name, p in self._declared.items() if not p.allowed)

    def description(self, name) -> str:
        return self._get(name).description

    def allows(self, names) -> bool:
        """Whether every permission in ``names`` is declared and allowed."""
        return all(
            name in self._declared and self._declared[name].allowed for name in names
        )

    def require(self, *names, what="This call"):
        """Raise :class:`PermissionDeniedError` unless every permission in ``names`` is
        allowed. ``what`` names the refused action."""
        for name in names:
            permission = self._declared.get(name)
            if permission is None:
                msg = f'{what}: permission "{name}" was never declared by the app'

                raise PermissionDeniedError(msg)
            if not permission.allowed:
                msg = (
                    f'{what}: permission "{name}" ({permission.description}) is off; '
                    f"only the people running the app can turn it on."
                )
                raise PermissionDeniedError(msg)

    # -------------------------------------------------------------------------
    # Launch options and lifecycle (driven by the MCP)
    # -------------------------------------------------------------------------

    def _deny_at_launch(self, names):
        self._launch_denied = frozenset(names)

    def _start(self):
        """Called when the server starts: report the launch names that match no
        permission. From then on, they refuse every agent call."""
        self._started = True
        unknown = self._unknown_at_launch()
        if unknown:
            logger.error(
                "--mcp-deny names %s, which this application does not declare "
                "(it declares: %s); every agent call is refused",
                ", ".join(unknown),
                ", ".join(self._declared) or "none",
            )

    def _unknown_at_launch(self) -> list[str]:
        return sorted(self._launch_denied - self._declared.keys())

    def _check_launch(self):
        """Refuse agent calls while a launch name matches no permission."""
        unknown = self._started and self._unknown_at_launch()
        if unknown:
            msg = (
                f"Agent access is refused: the application was launched denying "
                f"{', '.join(unknown)}, which it does not declare"
            )
            raise PermissionDeniedError(msg)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get(self, name) -> _Permission:
        try:
            return self._declared[name]
        except (KeyError, TypeError):
            msg = (
                f"No permission {name!r} is declared; declared: {list(self._declared)}"
            )
            raise KeyError(msg) from None

    def _ordered(self, names) -> tuple[str, ...]:
        """``names`` in declaration order."""
        return tuple(name for name in self._declared if name in names)

    def _required(self, name):
        return self._declared[name].requires

    def _requiring(self, name):
        return [n for n, p in self._declared.items() if name in p.requires]

    @staticmethod
    def _closure(names, step) -> set[str]:
        found, stack = set(), list(names)
        while stack:
            name = stack.pop()
            if name not in found:
                found.add(name)
                stack.extend(step(name))
        return found
