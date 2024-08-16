PRESET_KEY_SHARED_ARRAY_BUFFER = "SharedArrayBuffer"


class HttpHeader:
    """Helper class to construct and define http headers for the web server.
    This class is only driving the built-in aiohttp web server.
    But if can be manually leveraged to configure your own server implementation.
    """

    def __init__(self):
        self._headers = {}
        self._presets = {}

    @property
    def shared_array_buffer(self):
        """Return True if the shared array buffer was set"""
        return self._presets.get(PRESET_KEY_SHARED_ARRAY_BUFFER, False)

    @shared_array_buffer.setter
    def shared_array_buffer(self, v):
        """Enable/Disable http header to support shared array buffer"""
        self._presets[PRESET_KEY_SHARED_ARRAY_BUFFER] = bool(v)
        if self.shared_array_buffer:
            self.set_header("Cross-Origin-Opener-Policy", "same-origin")
            self.set_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.set_header("Access-Control-Allow-Origin", "*")
        else:
            self.remove_header("Cross-Origin-Opener-Policy")
            self.remove_header("Cross-Origin-Embedder-Policy")
            self.remove_header("Access-Control-Allow-Origin")

    def set_header(self, key, value):
        """Set given header key/value pair"""
        self._headers[key] = value

    def remove_header(self, key):
        """Discard given header key if present"""
        if key in self._headers:
            self._headers.pop(key)

    def get_header(self, key):
        """Return the current header value for the given key"""
        return self._headers.get(key)

    @property
    def headers(self):
        """Return currently configured headers"""
        return self._headers

    def apply(self):
        """Only apply on aiohttp backend"""
        from wslink.backends import aiohttp

        aiohttp.HTTP_HEADERS = self.headers
