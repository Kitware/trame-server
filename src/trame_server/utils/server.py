import socket
import sys
from urllib.parse import urlencode

from trame_server.auth import SECRET_PARAM

SECRET_PLACEHOLDER = "<secret>"


def http_scheme(options):
    """The scheme of the web server's URLs: ``https`` when it serves TLS
    (``--ssl``), else ``http``."""
    return "https" if getattr(options, "ssl", None) else "http"


def _secret_query(server):
    """The query string of the printed URLs, and a note to print after them.

    Any secret but the default is shown, unless --hide-secret: then a
    placeholder takes its place. The default secret adds nothing."""
    params = server.url_query_params
    if not params:
        return "", None
    if getattr(server.server_options, "hide_secret", False):
        query = f"?{SECRET_PARAM}={SECRET_PLACEHOLDER}"
        return query, "The secret is not shown (--hide-secret)."
    return f"?{urlencode(params)}", None


def print_informations(server):
    options = server.server_options
    query, note = _secret_query(server)
    scheme = http_scheme(options)
    local_url = f"{scheme}://{options.host}:{server.port}/{query}"
    print()
    print("App running at:")
    print(f" - Local:   {local_url}")

    try:
        try:
            host_ip = socket.gethostbyname(options.host)
        except Exception:
            host_name = socket.gethostname()
            host_ip = socket.gethostbyname(host_name)
        print(f" - Network: {scheme}://{host_ip}:{server.port}/{query}")
    except socket.gaierror:
        print(f" - Network: {scheme}://{options.host}:{server.port}/{query}")

    if note:
        print()
        print(note)

    print()
    print(
        "Note that for multi-users you need to use and configure a launcher.",
        flush=True,
    )
    sys.stdout.flush()


def print_mcp_informations(server):
    """Print how agents connect: the MCP URL, and the commands that start a Claude
    Code or Codex session with this server added."""
    from trame_server.mcp import claude_command, codex_command  # noqa: PLC0415

    mcp = server.root_server.mcp
    http = mcp.http
    url, name = http.url, mcp.name
    # A generated token is shown in full, since nobody else knows it. A token
    # the user set is shown as a placeholder
    token = http.token if http._token_generated else ("<token>" if http.token else None)
    print()
    print(f"MCP server available at {url}")
    print(f"  {claude_command(name, url, token)}")
    print(f"  {codex_command(name, url, token)}")
    if http._token_generated:
        print(
            "  (token generated because the server listens beyond localhost; "
            "set it with --mcp-http-token or TRAME_MCP_HTTP_TOKEN)"
        )
    print(flush=True)
