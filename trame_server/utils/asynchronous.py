import asyncio
import logging
from . import is_dunder, is_private

__all__ = [
    "create_task",
    "decorate_task",
    "create_state_queue_monitor_task",
    "StateQueue",
    "handle_task_result",
    "task",
]

QUEUE_EXIT = "STOP"


def handle_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task cancellation should not be logged as an error.
    except Exception:  # pylint: disable=broad-except
        logging.exception("Exception raised by task = %r", task)


def create_task(coroutine, loop=None):
    """
    Create a task from a coroutine while also attaching a done callback so any
    exception or error could be caught and reported.

    :param coroutine: A coroutine to execute as an independent task
    :param loop: Optionally provide the loop on which the task should be
                 scheduled on. By default we will use the current running loop.

    :return: The decorated task
    :rtype: asyncio.Task
    """
    if loop is None:
        loop = asyncio.get_event_loop()

    return decorate_task(loop.create_task(coroutine))


def decorate_task(task):
    """
    Decorate a task by attaching a done callback so any exception or error could
    be caught and reported.

    :param task: A coroutine to execute as an independent task
    :type task: asyncio.Task

    :return: The same task object
    :rtype: asyncio.Task
    """
    task.add_done_callback(handle_task_result)
    return task


async def _queue_update_state(server, queue, delay=1):
    _monitor_queue = True
    while _monitor_queue:
        if queue.empty():
            await asyncio.sleep(delay)
        else:
            msg = queue.get_nowait()
            if isinstance(msg, str):
                if msg == QUEUE_EXIT:
                    _monitor_queue = False
            else:
                with server.state:
                    server.state.update(msg)


def create_state_queue_monitor_task(server, queue, delay=1):
    """
    Create and schedule a task to watch over the provided queue
    to update a server state.
    This is especially useful when using a multiprocess executor
    and you want to report progress into your current server.

    :param server: A coroutine to execute as an independent task
    :type server: trame_server.core.Server

    :param queue: A queue instance meant to exchange state from
                  the parallel process to the given server
    :type queue: multiprocessing.Queue

    :param delay: Time to sleep in seconds before processing
                  the queue once emptied
    :type delay: float

    :return: The monitoring task
    :rtype: asyncio.Task
    """
    return create_task(_queue_update_state(server, queue, delay=delay))


class StateQueue:
    """
    Class use to decorate a multiprocessing.Queue inside your external
    process to simulate your server state object.

    :param queue: A queue instance meant to exchange state from the parallel
                  process to the given server
    :type queue: multiprocessing.Queue

    :param auto_flush: Should you manage the state update phase or just
                       propagate as soon as you update a property
    :type auto_flush: Boolean
    """

    def __init__(self, queue, auto_flush=True):
        self._queue = queue
        self._pending_update = {}
        self._pushed_state = {}
        self._auto_flush = auto_flush
        self._ctx_count = 0

    @property
    def queue(self):
        """Provide access to the decorated queue"""
        return self._queue

    def __getitem__(self, key):
        return self._pending_update.get(key, self._pushed_state.get(key))

    def __setitem__(self, key, value):
        self._pending_update[key] = value
        if self._auto_flush:
            self.flush()

    def __getattr__(self, key):
        if is_dunder(key):
            # Forward dunder calls to object
            return getattr(object, key)

        if is_private(key):
            return self.__dict__.get(key)

        return self.__getitem__(key)

    def __setattr__(self, key, value):
        if is_private(key):
            self.__dict__[key] = value
        else:
            self.__setitem__(key, value)

    def update(self, _dict):
        """
        Update the distributed state from a set of key/value pair

        :param _dict: A dict containing one or many key/value pair
        :type _dict: dict
        """
        self._pending_update.update(_dict)
        if self._auto_flush:
            self.flush()

    def flush(self):
        """Explicitly push any local change to the queue."""
        if len(self._pending_update):
            self._queue.put_nowait(self._pending_update)
            self._pushed_state.update(self._pending_update)
            self._pending_update = {}

    def exit(self):
        """Release the monitoring task as we are done with our work"""
        self._queue.put_nowait(QUEUE_EXIT)

    def __enter__(self):
        self._ctx_count += 1
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._ctx_count -= 1

        if self._ctx_count == 0:
            self.flush()
            self.exit()


def task(func):
    """Function decorator to make its async execution within a task"""

    def wrapper(*args, **kwargs):
        create_task(func(*args, **kwargs))

    return wrapper
