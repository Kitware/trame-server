import socket


def print_informations(server):
    args = server.cli.parse_known_args()[0]
    local_url = f"http://{args.host}:{args.port}/"
    print()
    print("App running at:")
    print(f" - Local:   {local_url}")

    try:
        host_name = socket.gethostname()
        host_ip = socket.gethostbyname(host_name)
        print(f" - Network: http://{host_ip}:{server.port}/")
    except socket.gaierror:
        pass

    print()
    print(
        "Note that for multi-users you need to use and configure a launcher.",
        flush=True,
    )
