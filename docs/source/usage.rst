Usage
=====

.. _installation:

Installation
------------

To use Trame Server, first install it using pip:

.. code-block:: console

   (.venv) $ pip install trame-server

Running
-------

To create a server, you can instantiate a ``Server`` object:

.. autoclass:: trame_server.Server

The ``name`` parameter can be used to specify the server name. For example:

>>> server = Server(name="my_server")
>>> server.name
'my_server'

WebSocket authentication
------------------------

Clients must provide a secret to connect to the WebSocket. The secret
comes from (in order of precedence):

* ``--authKeyFile PATH``: file whose (stripped) content is used as the secret.
* ``--authKey KEY``: secret provided directly on the command line.
* Otherwise, a random secret is generated every time the server starts.

The browser client reads the secret from the ``?secret=...`` URL parameter.
The URLs printed at startup, the browser opened automatically and the
desktop window (``--app``) already include it:

.. code-block:: console

   $ python app.py --server
   App running at:
    - Local:   http://localhost:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M
    - Network: http://127.0.0.1:8080/?secret=qcNXdzVSWzM9kiVkgSqh9Nk1lPiX0fBDTDaFtmCkx_M

To keep the secret out of the console output (and therefore out of any
captured logs), add ``--hide-secret``. With a generated secret, the printed
URLs then cannot be used to connect, so combine it with ``--authKey`` /
``--authKeyFile`` or with a launcher that delivers the secret to the client.

When building a client URL yourself (iframe, testing, ...), use
:attr:`trame_server.Server.url_query_params` once the server is started:

>>> from urllib.parse import urlencode
>>> url = f"http://localhost:{server.port}/?{urlencode(server.url_query_params)}"

Python clients (``trame_server.client.Client``) take the secret as an
argument of ``connect(url, secret=...)``.
