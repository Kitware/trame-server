from pathlib import Path


def print_banner(*args, **kwargs):
    txt = Path(__file__).with_name("banner.txt").read_text()
    print(txt, flush=True)
