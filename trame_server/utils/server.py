import sys
import socket


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
        pass

    print()
    print(
        "Note that for multi-users you need to use and configure a launcher.",
        flush=True,
    )
    sys.stdout.flush()
