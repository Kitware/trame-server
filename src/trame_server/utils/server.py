import socket
import sys

from trame_server.protocol import CoreServer


def print_informations(server):
    options = server.server_options
    hide_secret = getattr(options, "hide_secret", False)
    query = "" if hide_secret else CoreServer.url_query()
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

    if hide_secret:
        print()
        print("The '?secret=...' URL parameter is hidden (--hide-secret).")

    print()
    print(
        "Note that for multi-users you need to use and configure a launcher.",
        flush=True,
    )
    sys.stdout.flush()
