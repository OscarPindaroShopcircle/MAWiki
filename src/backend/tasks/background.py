import asyncio
from collections.abc import Coroutine
from typing import Any

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn_background(coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Schedule ``coro`` as a background task, keeping it alive until done.

    The event loop only keeps a *weak* reference to bare
    ``asyncio.create_task`` results, so a fire-and-forget task can be
    garbage-collected before it runs. Hold a strong reference until it
    finishes.
    """
    task = asyncio.create_task(coroutine)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task
