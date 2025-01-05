from trame.app import get_server
from trame.ui.html import DivLayout
from trame.widgets import html


def test_ui_vnode():
    server = get_server("test_ui_vnode")
    state = server.state
    state.ready()

    with DivLayout(server) as layout:
        server.ui.content(layout)

    assert state.trame__template_main == "<div >\n\n</div>"

    with server.ui.content:
        html.Div("Hello")

    assert state.trame__template_main == "<div >\n<div >\nHello\n</div>\n</div>"

    with server.ui.content:
        html.Div("World")

    assert (
        state.trame__template_main
        == "<div >\n<div >\nHello\n</div>\n<div >\nWorld\n</div>\n</div>"
    )

    with server.ui["content"].clear():
        html.Div("World")

    assert state.trame__template_main == "<div >\n<div >\nWorld\n</div>\n</div>"

    server.ui.clear()
    assert state.trame__template_main == "<div >\n<div >\nWorld\n</div>\n</div>"

    server.ui.flush_content()
    assert state.trame__template_main == "<div >\n\n</div>"

    server.ui.clear_layouts()
