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

To create a server, you can instantiate a `Server` object:

.. autoclass:: trame_server.Server

The ``name`` parameter can be used to specify the server name. For example:

>>> server = Server(name="my_server")
>>> server.name
'my_server'
