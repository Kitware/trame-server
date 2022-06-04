from .utils import is_dunder


class VirtualNodeManager:
    """VirtualNodeManager acts as a container for VirtualNode

    It allows widgets to be passed around that are not yet defined,
    and can be defined or re-defined later. For example:

    >>> with layout:
    ...    ui.hello_widget(layout)  # widget is currently undefined
    >>> with ui.hello_widget:
    ...   html.Div("Hello")
    """

    def __init__(self, server, vn_constructor=None):
        super().__setattr__("_server", server)
        super().__setattr__("_vn_dict", {})
        super().__setattr__("_vn_constructor", vn_constructor)

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        if is_dunder(name):
            return super().__getattr__(name)

        if name not in self._vn_dict:
            self._vn_dict[name] = self._vn_constructor(trame_server=self._server)

        return self._vn_dict[name]

    def set_vn_constructor(self, constructor):
        """Should not be called by user"""
        self._vn_constructor = constructor

    def clear_layouts(self):
        """
        Remove any reference to previously registered layouts
        across all VirutalNodes.
        """
        for vn in self._vn_dict.values():
            vn.clear_layouts()

    def flush_content(self):
        """Push all VirtualNode contents to registered layouts"""
        for vn in self._vn_dict.values():
            vn.flush_content()

    def clear(self):
        """Clear all VirtualNode contents"""
        for vn in self._vn_dict.values():
            vn.clear()
