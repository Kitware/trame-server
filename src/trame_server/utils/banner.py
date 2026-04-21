from pathlib import Path


def print_banner(*_, **__):
    txt = Path(__file__).with_name("banner.txt").read_text()
    print(txt, flush=True)
