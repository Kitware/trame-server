"""The MCP server of a trame server: ``server.mcp``."""

from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import dataclass, field

from trame_common.obj.mcp import permission_names

from trame_server.mcp.client import MCPClient
from trame_server.mcp.endpoint import HTTPTransport
from trame_server.mcp.objects import OBJECT_TOOLS, ObjectLayer
from trame_server.mcp.permissions import DENY_ENV, Permissions, launch_names
from trame_server.mcp.protocol import MCPProtocol
from trame_server.mcp.schema import (
    check_progress,
    docstring,
    function_input_schema,
    parameter_hints,
    type_to_schema,
)
from trame_server.mcp.typeinfo import tool_reference_schema

logger = logging.getLogger("trame_server.mcp")

__all__ = ["MCP", "MCPDisabledError"]

HTTP_TOKEN_ENV = "TRAME_MCP_HTTP_TOKEN"
LOG_ENV = "TRAME_MCP_LOG"

# How agents outside the process can connect (mcp.transports)
TRANSPORTS = ("http",)
DEFAULT_TRANSPORTS = ("http",)

# Claude Code rejects a tool whose full name mcp__<server>__<tool> is longer
MAX_FULL_TOOL_NAME = 64
# What the MCP spec allows in a tool name
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

LIVE_APP_INSTRUCTIONS = (
    "A live trame app, shared with its users: they see your changes at once."
)


class MCPDisabledError(PermissionError):
    """Raised for a call made while ``mcp.enabled`` is False."""


@dataclass
class ToolEntry:
    name: str
    description: str
    fn: object
    input_schema: dict | None = None  # None: derived from fn's signature
    annotations: dict | None = None
    concurrent: bool = False  # runs without the call lock
    requires: tuple = ()  # permission names (mcp.permissions)
    cached_schema: tuple = field(default=(None, None), repr=False)


@dataclass
class ResourceEntry:
    uri: str
    name: str
    description: str | None
    mime_type: str | None
    fn: object


@dataclass
class PromptEntry:
    name: str
    description: str | None
    arguments: list
    fn: object


def _tool_annotations(read_only, annotations):
    result = dict(annotations or {})
    if read_only:
        result["readOnlyHint"] = True
    return result or None


def _check_transports(names):
    unknown = [n for n in names if n not in TRANSPORTS]
    if unknown:
        msg = (
            f"Unknown MCP transport {unknown[0]!r}; available: {', '.join(TRANSPORTS)} "
            f"(an empty list serves agents in the process only)"
        )
        raise ValueError(msg)
    return tuple(dict.fromkeys(names))


def transports_withheld(args):
    """True when the command line serves no transport for the whole run, with
    ``--no-mcp`` or ``--no-mcp-transport``."""
    return getattr(args, "mcp", None) is False or bool(
        getattr(args, "mcp_no_transport", False)
    )


def launch_transports(args):
    """The transports the command line chooses: an empty tuple when it withholds
    them all or names ``none``, the names given to ``--mcp-transport``, or None
    when it leaves the choice to the application."""
    if transports_withheld(args):
        return ()
    names = getattr(args, "mcp_transport", None)
    if names is None:
        return None
    return () if names == ("none",) else names


class MCP:
    """The MCP server of a trame server, created on first access to
    ``server.mcp``. There is one per root server. Child servers share it, and
    the names they expose objects under go through their translator.

    It serves what the application declares: first-class tools, resources
    and prompts (``@server.mcp.tool``, ``server.mcp.resource(uri)``,
    ``@server.mcp.prompt``), and objects through the six ``object_*`` tools.
    Objects are the components and models whose class declares something,
    reached from the names the application exposes, and the ``state`` object.
    Nothing is served until ``enabled`` is set, in code or with ``--mcp`` at
    launch.

    Agents outside the process connect through ``transports``: HTTP by
    default, on the trame web server's port, with its options on ``http``.
    Agents inside the process, such as an assistant built into the
    application, use ``client()``.

    Every option is a settable attribute that can change at any time, and
    ``configure()`` sets several at once.
    """

    def __init__(self, server):
        self._server = server.root_server
        self._started = False
        self._ready = False
        self._name = None
        self._enabled = False
        self._transports = DEFAULT_TRANSPORTS
        self._http = HTTPTransport(self)
        self._concurrent_calls = False
        self._structured_content = False
        self._max_response_tokens = 8000
        self._permissions = Permissions()
        #: Text sent to agents when they connect, ahead of the overview trame
        #: generates from what the application exposes (default None).
        self.instructions = None

        self._tools: dict[str, ToolEntry] = {}
        self._resources: dict[str, ResourceEntry] = {}
        self._prompts: dict[str, PromptEntry] = {}

        self._objects = ObjectLayer(self)
        self._protocol = MCPProtocol(self)

        self._apply_launch_options()
        if self._server._mcp_bound:  # created once the server was already up
            self._start()
            if self._server.running:
                self._on_ready()

    # -------------------------------------------------------------------------
    # Life cycle (driven by the trame server)
    # -------------------------------------------------------------------------

    def _start(self):
        """Called when the server binds its port. From then on, launch options that
        turn something on or set a value no longer override assignments. Those
        that withhold something (``--no-mcp``, ``--no-mcp-transport`` and
        ``--mcp-deny``) still hold."""
        self._started = True
        self._permissions._start()
        self._objects.start()
        for entry in self._tools.values():
            unknown = [n for n in entry.requires if n not in self._permissions]
            if unknown:
                logger.warning(
                    "Tool %s requires undeclared permissions %s; it is never offered",
                    entry.name,
                    unknown,
                )
            self._check_length(entry.name, warn=True)
        if self._server._mcp_endpoint_mounted:
            self._http._start()

    def _on_ready(self):
        self._ready = True
        self._objects.audit()
        self._http._on_ready()

    # -------------------------------------------------------------------------
    # Launch options
    # -------------------------------------------------------------------------

    def _apply_launch_options(self):
        """Apply the command line (``Server.cli``) and the environment: ``enabled``,
        ``transports``, the HTTP ``token``, the call log and the denied
        permissions.

        They are the choice of the person running the application, so until the
        server starts they take precedence over what the application assigns,
        which only sets defaults. Those that withhold something (``--no-mcp``,
        ``--no-mcp-transport`` and ``--mcp-deny``) hold for the whole run.
        """
        args, _ = self._server.cli.parse_known_args()
        self._launch_options = {
            "enabled": getattr(args, "mcp", None),
            "transports": launch_transports(args),
            "transports_withheld": transports_withheld(args),
            "token": getattr(args, "mcp_http_token", None)
            or os.environ.get(HTTP_TOKEN_ENV)
            or None,
        }
        if self._launch_options["enabled"] is not None:
            self._enabled = self._launch_options["enabled"]
        if self._launch_options["transports"] is not None:
            self._transports = self._launch_options["transports"]
        if self._launch_options["token"] is not None:
            self._http._token = str(self._launch_options["token"])
        if getattr(args, "mcp_log", False) or os.getenv(LOG_ENV):
            # Like wslink's --debug, this only sets a level: the handlers are
            # the application's
            if logger.getEffectiveLevel() > logging.INFO:
                logger.setLevel(logging.INFO)
        # The flag and the variable both apply, since each withholds something
        self._permissions._deny_at_launch(
            launch_names(
                [*(getattr(args, "mcp_deny", None) or ()), os.environ.get(DENY_ENV)]
            )
        )

    def _launch_overrides(self, option):
        """True when a launch option decides ``option`` and the server has not
        started yet: the application's assignment is then only a default."""
        if self._started or self._launch_options.get(option) is None:
            return False
        logger.info(
            "MCP %s is set at launch; the application's value is ignored", option
        )
        return True

    # -------------------------------------------------------------------------
    # Options
    # -------------------------------------------------------------------------

    def configure(
        self,
        *,
        name=None,
        enabled=None,
        transports=None,
        concurrent_calls=None,
        structured_content=None,
        instructions=None,
        max_response_tokens=None,
    ):
        """Set several options at once; an option left as None is unchanged. This
        is the same as assigning the attributes one by one. The HTTP transport's
        options are set with ``http.configure()``."""
        options = {
            "name": name,
            "enabled": enabled,
            "transports": transports,
            "concurrent_calls": concurrent_calls,
            "structured_content": structured_content,
            "instructions": instructions,
            "max_response_tokens": max_response_tokens,
        }
        for key, value in options.items():
            if value is not None:
                setattr(self, key, value)

    @property
    def server(self):
        """The trame server this MCP server belongs to (a root server)."""
        return self._server

    @property
    def protocol(self):
        return self._protocol

    @property
    def name(self):
        """The name reported to clients and used in the connection commands
        (default: the trame server's name)."""
        return self._name or self._server.name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def enabled(self):
        """Whether agents can use what the application declares (default False).

        This is the one switch for agent access, whichever way agents connect,
        and it can change at any time. While it is False, every call is refused
        and the HTTP endpoint answers 503. ``--mcp`` at launch takes precedence
        over values the application sets before the server starts; once the
        server runs, every assignment applies. ``--no-mcp`` keeps access off for
        the whole run (:attr:`enabled_locked`).
        """
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        if value and self.enabled_locked:
            logger.info("--no-mcp keeps agent access off for this run")
            return
        if self._launch_overrides("enabled"):
            return
        self._enabled = bool(value)
        if self._enabled:
            self._http._announce()

    @property
    def enabled_locked(self):
        """True when ``--no-mcp`` keeps agent access off for the whole run. Turning
        access on is then ignored, so a UI should disable its switch."""
        return self._launch_options["enabled"] is False

    @property
    def transports(self):
        """How agents outside the process connect (default ``("http",)``): a tuple
        of transport names, empty when only agents inside the process may connect.

        It can change at any time; while ``"http"`` is left out, the HTTP
        endpoint answers 503. ``--mcp-transport`` at launch takes precedence over
        values the application sets before the server starts.
        ``--no-mcp-transport`` and ``--no-mcp`` serve no transport for the whole
        run (:attr:`transports_locked`).
        """
        return self._transports

    @transports.setter
    def transports(self, value):
        names = _check_transports((value,) if isinstance(value, str) else value)
        if names and self.transports_locked:
            flag = "--no-mcp" if self.enabled_locked else "--no-mcp-transport"
            logger.info("%s keeps agents in other processes out for this run", flag)
            return
        if self._launch_overrides("transports"):
            return
        self._transports = names
        if "http" in names:
            self._http._announce()

    @property
    def transports_locked(self):
        """True when ``--no-mcp-transport`` or ``--no-mcp`` serve no transport for
        the whole run. Adding a transport is then ignored, so a UI should disable
        its switch."""
        return self._launch_options["transports_withheld"]

    def client(self, name="in-process"):
        """A client for an agent inside the application's process
        (:class:`MCPClient`). It lists and calls what agents may use, without a
        transport but under the same rules (``enabled``, permissions). ``name``
        identifies it in the call log."""
        return MCPClient(self, name)

    @property
    def http(self):
        """The HTTP transport's options (:class:`HTTPTransport`): ``path``,
        ``token``, ``allowed_origins`` and the read-only ``url``."""
        return self._http

    @property
    def permissions(self):
        """The permissions: capabilities that the people running the application can
        withhold from agents. ``declare()`` each one, then name the permissions
        that a tool, method, property or constructor needs with ``requires=``.
        ``--mcp-deny`` or ``TRAME_MCP_DENY`` deny permissions for the whole run
        (``permissions.locked``)."""
        return self._permissions

    @property
    def concurrent_calls(self):
        """When False (default), agent calls run one at a time, except those
        declared with ``concurrent=True``. When True, every call may run
        while others are in progress."""
        return self._concurrent_calls

    @concurrent_calls.setter
    def concurrent_calls(self, value):
        self._concurrent_calls = bool(value)

    @property
    def structured_content(self):
        """Whether to also send a tool's dict result as ``structuredContent``
        (default False). The result is always sent as compact JSON text too."""
        return self._structured_content

    @structured_content.setter
    def structured_content(self, value):
        self._structured_content = bool(value)

    @property
    def max_response_tokens(self):
        """The maximum size of a reply from the ``object_*`` tools, in tokens of
        about 4 characters (default 8000). A reply cut to fit says how to get the
        rest."""
        return self._max_response_tokens

    @max_response_tokens.setter
    def max_response_tokens(self, value):
        if not isinstance(value, int) or value < 500:
            msg = (
                f"max_response_tokens must be an integer of at least 500, got {value!r}"
            )
            raise ValueError(msg)
        self._max_response_tokens = value

    def _agent_instructions(self):
        """What clients receive as ``instructions``: the application's own
        text, then a generated overview."""
        lines = [LIVE_APP_INSTRUCTIONS, *self._objects.instructions()]
        denied = self._permissions.denied
        if denied:
            names = ", ".join(
                f"{n} ({self._permissions.description(n)})" for n in denied
            )
            lines.append(
                f"Turned off in this application: {names}. What needs them is not "
                f"offered, and calls to it are refused."
            )
        overview = "\n".join(lines)
        if self.instructions:
            return f"{self.instructions.strip()}\n\n{overview}"
        return overview

    def _check_enabled(self):
        if not self._enabled:
            msg = "MCP access is currently disabled by the application"
            raise MCPDisabledError(msg)
        self._permissions._check_launch()

    # -------------------------------------------------------------------------
    # First-class tools, resources and prompts
    # -------------------------------------------------------------------------

    def tool(
        self,
        fn=None,
        *,
        name=None,
        description=None,
        read_only=False,
        annotations=None,
        concurrent=False,
        requires=None,
    ):
        """Make a function, or a bound method, a tool. Use it as a decorator or call
        it: ``server.mcp.tool(self.screenshot)``.

        The type hints give the input schema. ``Annotated[T, "description",
        {json-schema}]`` adds a description and constraints, and a parameter
        typed with a component or model class takes that object's id or name.
        Results: a ``str`` is sent as text, an ``Image`` as an image (a list of
        them as several), and anything else as compact JSON text (``null`` for
        None).

        :param name: the tool name (default: the function's).
        :param description: the text agents read (default: the docstring).
        :param read_only: True when it changes nothing (``readOnlyHint``).
        :param annotations: extra MCP tool annotations.
        :param concurrent: True to let it run while other agent calls are in
            progress.
        :param requires: the permission, or list of permissions, that a call
            needs.
        """

        def decorate(f):
            self._add_tool(
                f,
                name=name,
                description=description,
                annotations=_tool_annotations(read_only, annotations),
                concurrent=concurrent,
                requires=requires,
            )
            return f

        if fn is None:
            return decorate
        return decorate(fn)

    def resource(self, uri, *, name=None, description=None, mime_type=None):
        """Serve what a function returns as the resource ``uri``. This returns a
        decorator; for a method, call it as
        ``server.mcp.resource(uri)(self.guide)``."""

        def decorate(f):
            self._add_resource(
                f, uri=uri, name=name, description=description, mime_type=mime_type
            )
            return f

        return decorate

    def prompt(self, fn=None, *, name=None, description=None):
        """Make a function, or a bound method, a prompt. Use it as a decorator or
        call it."""

        def decorate(f):
            self._add_prompt(f, name=name, description=description)
            return f

        if fn is None:
            return decorate
        return decorate(fn)

    def _check_length(self, tool_name, warn=False):
        full = f"mcp__{self.name}__{tool_name}"
        if len(full) <= MAX_FULL_TOOL_NAME:
            return
        msg = (
            f"Tool {tool_name!r}: its full name {full!r} has {len(full)} characters; "
            f"clients such as Claude Code reject more than {MAX_FULL_TOOL_NAME}. "
            f"Shorten the tool name or mcp.name"
        )
        if warn:
            logger.warning(msg)
            return
        raise ValueError(msg)

    def _add_tool(
        self,
        fn,
        name=None,
        description=None,
        annotations=None,
        concurrent=False,
        requires=None,
    ):
        tool_name = name or fn.__name__
        if tool_name in OBJECT_TOOLS:
            msg = f"{tool_name!r} is the name of a built-in object tool; choose another"
            raise ValueError(msg)
        if tool_name in self._tools:
            msg = f"A tool named {tool_name!r} is already registered"
            raise ValueError(msg)
        if not isinstance(tool_name, str) or not TOOL_NAME.match(tool_name):
            msg = f"A tool name is 1-128 of A-Z a-z 0-9 _ - (and .), got {tool_name!r}"
            raise ValueError(msg)
        if "." in tool_name:
            logger.warning(
                "Tool %r: OpenAI-style function calling rejects dots in names",
                tool_name,
            )
        self._check_length(tool_name)
        check_progress(fn, f"Tool {tool_name!r}")
        self._tools[tool_name] = ToolEntry(
            name=tool_name,
            description=description or docstring(fn) or "",
            fn=fn,
            annotations=annotations,
            concurrent=bool(concurrent),
            requires=permission_names(requires),
        )

    def _add_builtin_tool(
        self, fn, name, description, annotations=None, concurrent=False
    ):
        """Add a built-in tool, whose input schema comes from ``fn``'s signature."""
        self._tools[name] = ToolEntry(
            name=name,
            description=description,
            fn=fn,
            input_schema=function_input_schema(fn),
            annotations=annotations,
            concurrent=concurrent,
        )

    def _input_schema(self, entry):
        """The tool's input schema. A schema derived from the signature names object
        types, so it is computed again whenever they may have changed."""
        if entry.input_schema is not None:
            return entry.input_schema
        from trame_common.obj.mcp import options_version  # noqa: PLC0415

        version = options_version()
        cached_version, schema = entry.cached_schema
        if cached_version != version:
            schema = function_input_schema(entry.fn, ref=tool_reference_schema)
            entry.cached_schema = (version, schema)
        return schema

    def _add_resource(self, fn, uri, name=None, description=None, mime_type=None):
        if uri in self._resources:
            msg = f"A resource with uri {uri!r} is already registered"
            raise ValueError(msg)
        self._resources[uri] = ResourceEntry(
            uri=uri,
            name=name or fn.__name__,
            description=description or docstring(fn),
            mime_type=mime_type,
            fn=fn,
        )

    def _add_prompt(self, fn, name=None, description=None):
        prompt_name = name or fn.__name__
        if prompt_name in self._prompts:
            msg = f"A prompt named {prompt_name!r} is already registered"
            raise ValueError(msg)

        hints = parameter_hints(fn)
        arguments = []
        for pname, param in inspect.signature(fn).parameters.items():
            if pname == "self" or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            argument = {
                "name": pname,
                "required": param.default is inspect.Parameter.empty,
            }
            # Annotated[str, "description"], as for tool parameters
            argument_description = type_to_schema(hints.get(pname)).get("description")
            if argument_description:
                argument["description"] = argument_description
            arguments.append(argument)
        self._prompts[prompt_name] = PromptEntry(
            name=prompt_name,
            description=description or docstring(fn),
            arguments=arguments,
            fn=fn,
        )

    def list_tools(self):
        """The tools offered to agents: those whose permissions are all allowed.
        ``get_tool`` finds the other tools too, so that a call to one of them is
        refused with the reason."""
        return [t for t in self._tools.values() if self._permissions.allows(t.requires)]

    def get_tool(self, name):
        return self._tools.get(name)

    def list_resources(self):
        return list(self._resources.values())

    def get_resource(self, uri):
        return self._resources.get(uri)

    def list_prompts(self):
        return list(self._prompts.values())

    def get_prompt(self, name):
        return self._prompts.get(name)

    # -------------------------------------------------------------------------
    # Objects
    # -------------------------------------------------------------------------

    def expose_object(self, source, name, *, description=None, read_only=False):
        """Expose an object to agents under ``name``.

        :param source: a component or model, or a function that returns one (or
            None). trame calls the function on every agent request, so
            ``lambda: self.active`` follows reassignment. A name holds a
            component weakly and a model strongly.
        :param name: must start with a letter or an underscore, and ``state`` is
            reserved. A name that already exposes something else must be
            withdrawn first, while exposing the same source again updates its
            options. Like a state key, the name goes through the server's
            translator: on a child server with the prefix ``left_``, agents see
            ``left_viewer`` for ``viewer``.
        :param description: what this object is for in the application. Agents
            read it next to the name; the class already says what the type is.
        :param read_only: agents can call only ``read_only`` methods, and write
            no property, of what they reach only this way. Reached by id, an
            object is read-only too, unless a writable name (or a function's
            result under one), or a property of a writable object, also reaches
            it.
        """
        self._objects.expose(source, self._translate(name), description, read_only)

    def unexpose_object(self, name):
        """Withdraw a name given with :meth:`expose_object`."""
        self._objects.unexpose(self._translate(name))

    def _translate(self, name):
        return self._server.translator.translate_key(name)

    def describe(self, cls):
        """What agents currently see of ``cls``, as ``object_types`` shows it, or
        None when it is hidden. Pass ``"State"`` for the state object."""
        return self._objects.describe_class(cls)

    def _remove_object(self, obj):
        """Withdraw every name exposing ``obj``."""
        self._objects.remove(obj)

    def _add_component_tools(self, component):
        """Add the tools, resources and prompts that a newly built component marks
        (``@mcp.tool``, ``@mcp.resource``, ``@mcp.prompt``): all of them, or none
        when one cannot be added."""
        from trame_common.obj.mcp import (  # noqa: PLC0415
            PROMPT_MARKER,
            RESOURCE_MARKER,
            TOOL_MARKER,
            first_class_members,
        )

        cls = type(component)
        added = []
        try:
            for attr, marker, options in first_class_members(cls):
                fn = getattr(component, attr)
                if marker == TOOL_MARKER:
                    key = options["name"] or attr
                    self._check_free(self._tools, key, "tool", cls)
                    self._add_tool(
                        fn,
                        name=options["name"],
                        description=options["description"],
                        annotations=_tool_annotations(
                            options["read_only"], options["annotations"]
                        ),
                        concurrent=options["concurrent"],
                        requires=options["requires"],
                    )
                    added.append((self._tools, key))
                elif marker == RESOURCE_MARKER:
                    key = options["uri"]
                    self._check_free(self._resources, key, "resource", cls)
                    self._add_resource(fn, **options)
                    added.append((self._resources, key))
                elif marker == PROMPT_MARKER:
                    key = options["name"] or attr
                    self._check_free(self._prompts, key, "prompt", cls)
                    self._add_prompt(fn, **options)
                    added.append((self._prompts, key))
        except Exception:
            for registry, key in added:
                del registry[key]
            raise

    @staticmethod
    def _check_free(registry, key, item_type, cls):
        entry = registry.get(key)
        owner = getattr(getattr(entry, "fn", None), "__self__", None)
        if entry is not None and isinstance(owner, cls):
            msg = (
                f"{cls.__name__} {owner._id} already added the {item_type} {key!r}: "
                f"@mcp.tool, @mcp.resource and @mcp.prompt are for components built "
                f"once. Unbind the first (_unbind_annotated_methods()) before building "
                f"another, or register per-instance tools with server.mcp.tool()"
            )
            raise ValueError(msg)

    def _remove_component_tools(self, component):
        """Remove what an unbound component added."""
        for registry in (self._tools, self._resources, self._prompts):
            for key, entry in list(registry.items()):
                if getattr(entry.fn, "__self__", None) is component:
                    del registry[key]

    def _expose_state(self, key, **options):
        self._objects.expose_state(key, **options)

    def _unexpose_state(self, *keys):
        self._objects.state.unexpose(*keys)

    def _exposes_anything(self):
        return bool(
            self._objects.exposes_anything()
            or self._resources
            or self._prompts
            or any(name not in OBJECT_TOOLS for name in self._tools)
        )


class ChildMCP:
    """What ``server.mcp`` returns on a child server: the root's MCP, except that
    the names it exposes objects under go through the child's translator, as
    its state keys and controller names do."""

    def __init__(self, mcp, translator):
        object.__setattr__(self, "_mcp", mcp)
        object.__setattr__(self, "_translator", translator)

    def __getattr__(self, name):
        return getattr(self._mcp, name)

    def __setattr__(self, name, value):
        setattr(self._mcp, name, value)

    def _translate(self, name):
        return self._translator.translate_key(name)

    # The root's own, translating with this translator
    expose_object = MCP.expose_object
    unexpose_object = MCP.unexpose_object
