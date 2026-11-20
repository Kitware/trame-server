.. |pypi_download| image:: https://kitware.github.io/trame/downloads/trame-server.svg

trame-server: server implementation of trame |pypi_download|
===========================================================================

.. image:: https://github.com/Kitware/trame-server/actions/workflows/test_and_release.yml/badge.svg
    :target: https://github.com/Kitware/trame-server/actions/workflows/test_and_release.yml
    :alt: Test and Release

.. image:: https://codecov.io/github/Kitware/trame-server/graph/badge.svg?token=VeOing7nYT
    :target: https://codecov.io/github/Kitware/trame-server
    :alt: Code Coverage

trame-server is the server implementation of `trame <https://kitware.github.io/trame/>`_.
This Python library provide the server implementation of the shared state and controller along with the definition of the web server.
The web server aims to be flexible so it can be use within a Jupyter environment or as a standalone desktop application.

This package is not supposed to be used by itself but rather should come as a dependency of **trame**.
For any specificity, please refer to `the trame documentation <https://kitware.github.io/trame/>`_.


Installing
-----------------------------------------------------------

trame-server can be installed with `pip <https://pypi.org/project/trame-server/>`_:

.. code-block:: bash

    pip install trame-server

Usage
-----------------------------------------------------------

The `Trame Tutorial <https://kitware.github.io/trame/guide/tutorial>`_ is the place to go to learn how to use the library and start building your own application.

The `API Reference <https://trame.readthedocs.io/en/latest/index.html>`_ documentation provides API-level documentation.


**Environments variables**

* **TRAME_LOG_NETWORK**     : Path to log file for capturing network exchange. (default: None)
* **TRAME_WS_MAX_MSG_SIZE** : Maximum size in bytes of any ws message. (default: 10MB)
* **TRAME_WS_HEART_BEAT**   : Time in second before assuming the server is non-responsive. (default: 30s)
* **TRAME_DESKTOP_DEBUG**   : If defined it will allow user to inspect the web content in desktop mode
* **TRAME_SERVER**          : If set to true, this will prevent browser from opening by default


**WebSocket authentication**

Clients must provide a secret to connect to the WebSocket. The secret
comes from (in order of precedence):

* ``--authKeyFile PATH`` : File whose (stripped) content is used as the secret.
* ``--authKey KEY``      : Secret provided directly on the command line
  (visible to other users of the machine in the process list).
* ``--authKey auto``     : A random secret generated every time the server starts.
* Otherwise, wslink's well-known default secret, which every client already
  knows. Set a secret (``--authKey auto`` is the simplest) to keep other web
  pages from driving your app.

The browser client reads the secret from the ``?secret=...`` URL parameter.
The browser opened automatically and the desktop window (``--app``) include
it whenever it is not the default, and so do the URLs printed at startup.
With ``--authKey auto``::

    App running at:
     - Local:   http://localhost:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M
     - Network: http://127.0.0.1:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M

The browser opened automatically gets the URL on its command line, which
other users of the machine can see in the process list. On a shared machine,
add ``--server`` and open the printed URL yourself.

When a page is loaded with the right secret, the server also sets an
HttpOnly cookie, so reloading the page or opening the app in another tab
keeps working once the client has removed the secret from its URL. The
cookie only authenticates WebSocket connections opened by the app's own
pages: other pages and programs must send the secret themselves, and are
then accepted wherever they come from.
The cookie requires the default aiohttp backend. A browser keeps the
cookies of the 20 trame servers of a host it opened most recently: opening
one more removes the oldest cookie, and that app then needs its URL with the
secret again to reconnect.

Add ``--hide-secret`` to keep the secret out of the console output, and
therefore out of any captured logs: for example with ``--authKeyFile``, or
behind a launcher, which saves the output of each process in a log file.
The printed URLs then show ``?secret=<secret>`` instead.

When building a client URL yourself (iframe, testing, ...), use
``server.url_query_params`` once the server is started to get the
parameters to append (e.g. ``{"secret": "..."}``, or ``{}`` with the
default secret).

To accept other tokens as well, or to add conditions, replace the
protocol's ``validateToken``: wslink calls it with the value each client
sends as its secret (the ``?secret=...`` URL parameter for the browser
client). Do it in a function registered with
``server.add_protocol_to_configure()`` before starting the server: trame
calls it at startup with its protocol. Keep trame's own check to extend it
rather than replace it:

.. code-block:: python

    issued_tokens = {"token-for-alice", "token-for-bob"}


    def accept_issued_tokens(protocol):
        trame_check = protocol.validateToken  # the secret, or the cookie

        async def validate_token(token, client_id):
            return await trame_check(token, client_id) or token in issued_tokens

        protocol.validateToken = validate_token


    server.add_protocol_to_configure(accept_issued_tokens)

The replacement must be a coroutine taking ``(token, client_id)``.
Combined with ``or``, it keeps accepting everything trame accepts, which
without ``--authKey`` includes wslink's well-known default secret.


**Life cycle callbacks**

Life cycle events are directly managed on the application controller
and are prefixed with ``on_*``.

* **on_server_start**     : Executed at server.start() call while passing the server as argument.
* **on_server_bind**      : WSLinkServer is getting bound to trame so you can attach your own routes. Its instance will be passed as argument to callback.
* **on_server_ready**     : All protocols initialized and available for client to connect
* **on_client_connected** : Connection established to server
* **on_client_exited**    : Linked to browser "beforeunload" event
* **on_server_exited**    : Trame is exiting its event loop

* **on_error**            : JS error forwarded (msg:str) on the python
* **on_exception**        : Server exception occurred when interacting with the UI, in a ``@state.change`` listener (sync or async) or in a controller task (``ctrl.add_task``). The exception instance is provided as arg.

* **on_server_reload**    : If callback registered it can be use to hot_reload methods like the UI.


License
-----------------------------------------------------------

trame-server is made available under the Apache License, Version 2.0. For more details, see `LICENSE <https://github.com/Kitware/trame-server/blob/master/LICENSE>`_


Community
-----------------------------------------------------------

`Trame <https://kitware.github.io/trame/>`_ | `Discussions <https://github.com/Kitware/trame/discussions>`_ | `Issues <https://github.com/Kitware/trame/issues>`_ | `Contact Us <https://www.kitware.com/contact-us/>`_

.. image:: https://zenodo.org/badge/410108340.svg
    :target: https://zenodo.org/badge/latestdoi/410108340


Enjoying trame?
-----------------------------------------------------------

Share your experience `with a testimonial <https://github.com/Kitware/trame/issues/18>`_ or `with a brand approval <https://github.com/Kitware/trame/issues/19>`_.

Development
-----------------------------------------------------------

Install the library in dev mode

.. code-block:: bash

    # Create venv and install all dependencies
    uv sync --all-extras --dev

    # Activate environment
    source .venv/bin/activate

    # Install commit analysis
    pre-commit install
    pre-commit install --hook-type commit-msg

    # Run pre-commit checks
    pre-commit run --all-files
