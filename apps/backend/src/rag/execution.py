"""有界的 I/O：已取消的等待者无法释放正在工作的工作线程槽位。"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from functools import partial
from time import perf_counter

deadline_context = ContextVar("rag_deadline", default=None)


def remaining_timeout(default=60):
    deadline = deadline_context.get()
    if deadline is None:
        return default
    remaining = deadline - perf_counter()
    if remaining <= 0:
        raise TimeoutError
    return min(default, remaining)


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-io")
_slots = threading.BoundedSemaphore(4)


async def run_sync(function, /, **kwargs):
    while not _slots.acquire(blocking=False):
        await asyncio.sleep(0.01)
    try:
        future = _executor.submit(copy_context().run, partial(function, **kwargs))
    except BaseException:
        _slots.release()
        raise
    future.add_done_callback(lambda _: _slots.release())
    wrapped = asyncio.wrap_future(future)
    # 即使请求已超时、不再等待结果，也要取回迟到的异常，避免异常被吞掉。
    wrapped.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    return await asyncio.shield(wrapped)
