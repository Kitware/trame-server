def open_browser(server):
    args = server.cli.parse_known_args()[0]
    local_url = f"http://{args.host}:{server.port}/"
    try:
        import webbrowser
        import asyncio

        loop = asyncio.get_event_loop()
        loop.call_later(0.1, lambda: webbrowser.open(local_url))
        print(
            "And to prevent your browser from opening, "
            "add '--server' to your command line."
        )
    except Exception:
        pass
