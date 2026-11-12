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
* ``--authKey KEY``      : Secret provided directly on the command line.
* Otherwise, a random secret is generated every time the server starts.

The browser client reads the secret from the ``?secret=...`` URL parameter,
so the URLs printed at startup, the browser opened automatically and the
desktop window (``--app``) already include it::

    App running at:
     - Local:   http://localhost:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M
     - Network: http://127.0.0.1:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M

Use ``--hide-secret`` to keep the secret out of the console output (and
therefore out of any captured logs). With a generated secret this means
the printed URLs cannot be used to connect, so combine it with
``--authKey`` / ``--authKeyFile`` or with a launcher that delivers the
secret to the client.

When building a client URL yourself (iframe, testing, ...), use
``server.url_query_params`` once the server is started to get the
parameters to append (e.g. ``{"secret": "..."}``).


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
