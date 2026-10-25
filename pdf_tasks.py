"""Background execution with a timeout for slow work such as PDF extraction (Phase 0.8). No Streamlit imports."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 120.0


class TaskTimeout(TimeoutError):
    """Raised when background work does not finish inside its time limit."""


def run_with_timeout(
    func: Callable[[], T],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = 0.25,
    on_tick: Callable[[float], None] | None = None,
) -> T:
    """Run ``func`` on a worker thread and wait up to ``timeout_s`` seconds.

    ``on_tick(fraction_of_timeout_elapsed)`` is called every ``poll_s`` seconds so a UI can show progress
    while the caller's thread stays responsive. Exceptions from ``func`` propagate. On timeout the worker
    cannot be killed (Python limitation) but is abandoned and ``TaskTimeout`` is raised, so the UI never
    freezes; the abandoned thread ends when ``func`` returns.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func)
    start = time.monotonic()
    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_s:
                raise TaskTimeout(f"Timed out after {timeout_s:.0f} seconds.")
            try:
                return future.result(timeout=min(poll_s, max(0.0, timeout_s - elapsed)))
            except FutureTimeout:
                if on_tick is not None:
                    on_tick(min(1.0, (time.monotonic() - start) / timeout_s))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
