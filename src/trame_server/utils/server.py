import socket
import sys
from urllib.parse import urlencode

from trame_server.auth import SECRET_PARAM

SECRET_PLACEHOLDER = "<secret>"


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
    local_url = f"http://{options.host}:{server.port}/{query}"
    print()
    print("App running at:")
    print(f" - Local:   {local_url}")

    try:
        try:
            host_ip = socket.gethostbyname(options.host)
        except Exception:
            host_name = socket.gethostname()
            host_ip = socket.gethostbyname(host_name)
        print(f" - Network: http://{host_ip}:{server.port}/{query}")
    except socket.gaierror:
        print(f" - Network: http://{options.host}:{server.port}/{query}")

    if note:
        print()
        print(note)

    print()
    print(
        "Note that for multi-users you need to use and configure a launcher.",
        flush=True,
    )
    sys.stdout.flush()
