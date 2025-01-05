import asyncio
import pytest

import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

from trame.app import get_server, asynchronous


@pytest.mark.asyncio
async def test_thread_state_sync():
    running_states = []
    value_changes = []

    MULTI_PROCESS_MANAGER = multiprocessing.Manager()
    SPAWN = multiprocessing.get_context("spawn")
    PROCESS_EXECUTOR = ProcessPoolExecutor(1, mp_context=SPAWN)

    loop = asyncio.get_event_loop()
    queue = MULTI_PROCESS_MANAGER.Queue()

    server = get_server("test_thread_state_sync")
    server.state.running = False
    server.state.a = 0

    @server.state.change("running")
    def on_running_change(running, **_):
        running_states.append(running)

    @server.state.change("a")
    def on_a_change(a, **_):
        value_changes.append(a)

    server.start(exec_mode="task", port=0)
    assert await server.ready

    def exec_in_thread(queue):
        with asynchronous.StateQueue(queue) as state:
            assert state.queue is queue

            state.running = True

            state.update(
                {
                    "b": 10,
                    "c": 20,
                }
            )

            for i in range(10):
                time.sleep(0.1)
                state.a = i
                assert state.a == i
                assert state["a"] == i

            state.running = False

    asynchronous.decorate_task(
        loop.run_in_executor(
            PROCESS_EXECUTOR,
            exec_in_thread(queue),
        )
    )
    asynchronous.create_state_queue_monitor_task(server, queue)

    previous_size = len(value_changes)
    while len(value_changes) < 10:
        await asyncio.sleep(0.15)
        assert len(value_changes) > previous_size
        previous_size = len(value_changes)

    assert running_states == [False, True, False]

    assert server.state.b == 10
    assert server.state.c == 20

    await server.stop()


@pytest.mark.asyncio
async def test_task_decorator():
    bg_update = "idle"

    @asynchronous.task
    async def run_something():
        nonlocal bg_update
        bg_update = "ok"

    run_something()
    assert bg_update == "idle"
    await asyncio.sleep(0.1)
    assert bg_update == "ok"
