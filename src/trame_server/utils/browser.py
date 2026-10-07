def open_browser(server):
    args = server.cli.parse_known_args()[0]
    local_url = f"http://{args.host}:{server.port}/"
    try:
        import webbrowser  # noqa: PLC0415

        from .asynchronous import get_event_loop  # noqa: PLC0415

        loop = get_event_loop()
        loop.call_later(0.1, lambda: webbrowser.open(local_url))
        print(
            "And to prevent your browser from opening, "
            "add '--server' to your command line."
        )
    except Exception:
        pass
