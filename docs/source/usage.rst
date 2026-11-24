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
* ``--authKey KEY``: secret provided directly on the command line (visible
  to other users of the machine in the process list).
* ``--authKey auto``: a random secret generated every time the server starts.
* Otherwise, wslink's well-known default secret, which every client already
  knows. Set a secret (``--authKey auto`` is the simplest) to keep other web
  pages from driving your app.

The browser client reads the secret from the ``?secret=...`` URL parameter.
The browser opened automatically and the desktop window (``--app``) include
it whenever it is not the default, and so do the URLs printed at startup.
With ``--authKey auto``:

.. code-block:: console

   $ python app.py --server --authKey auto
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
:attr:`trame_server.Server.url_query_params` once the server is started
(``{}`` with the default secret):

>>> from urllib.parse import urlencode
>>> url = f"http://localhost:{server.port}/?{urlencode(server.url_query_params)}"

Python clients (``trame_server.client.Client``) take the secret as an
argument of ``connect(url, secret=...)``.

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
