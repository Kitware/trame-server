# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "trame",
#     "trame-vtk",
#     "trame-vuetify",
# ]
# ///
from trame.app import TrameApp, demo
from trame.ui.html import DivLayout
from trame.widgets import html


class App(TrameApp):
    def __init__(self, server=None):
        super().__init__(server)
        self.sub_app = demo.Cone("internal")
        self.task = None
        self._build_ui()

    async def start(self):
        if self.state.running:
            return

        self.sub_app.server.start(exec_mode="task", port=0)
        await self.sub_app.server.ready
        self.state.running = True
        port = self.sub_app.server.port
        self.state.url = f"http://localhost:{port}/"

    async def stop(self):
        if not self.state.running:
            return

        await self.sub_app.server.stop()
        self.state.running = False
        self.state.url = ""

    def _build_ui(self):
        with DivLayout(self.server) as self.ui:
            html.Button("Stop", click=self.stop, v_if=("running", False))
            html.Button("Start", click=self.start, v_else=True)
            html.A("{{ url }}", href=("url", ""), v_show="running", target="_blank")


def main():
    app = App()
    app.server.start()


if __name__ == "__main__":
    main()
