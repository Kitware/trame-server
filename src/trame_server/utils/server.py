import socket
import sys


def print_informations(server):
    options = server.server_options
    local_url = f"http://{options.host}:{server.port}/"
    print()
    print("App running at:")
    print(f" - Local:   {local_url}")

    try:
        try:
            host_ip = socket.gethostbyname(options.host)
        except Exception:
            host_name = socket.gethostname()
            host_ip = socket.gethostbyname(host_name)
        print(f" - Network: http://{host_ip}:{server.port}/")
    except socket.gaierror:
        print(f" - Network: http://{options.host}:{server.port}/")

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
