from argparse import ArgumentParser

from trame.app import get_server


def main():
    parser = ArgumentParser()
    parser.add_argument("--f", dest="foo")
    parser.parse_known_args()

    server = get_server("test_cli")
    server.start(timeout=1, open_browser=False)


if __name__ == "__main__":
    main()
