from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html


def test_namespace_template():
    server = get_server("test_namespace_template")
    child_server = server.create_child_server(prefix="child_")
    child_server.state.a = 10

    layout = DivLayout(child_server)
    with layout:
        html.Div("{{ a }}")

    assert layout.html == "<div >\n<div >\n{{ child_a }}\n</div>\n</div>"
    assert child_server.translator("a") == "child_a"
