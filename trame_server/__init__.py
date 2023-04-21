from .core import Server
from .client import Client
from .utils.version import get_version

__version__ = get_version("trame-server")
__license__ = "Apache License 2.0"
__all__ = [
    "Server",
    "Client",
]
