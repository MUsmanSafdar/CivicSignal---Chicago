"""Small sliding-window rate limiter for chat input (Phase 2.2). No Streamlit imports.

This is a per-session guard against accidental or scripted floods. It is not a substitute for network-level
limits (Azure Front Door or API Management), which are described in AZURE_DEPLOYMENT_NOTES.md.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Allow at most ``max_events`` calls in any ``window_s`` seconds. Time is injectable for tests."""

    def __init__(self, max_events: int = 12, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        if max_events < 1 or window_s <= 0:
            raise ValueError("max_events must be at least 1 and window_s positive")
        self.max_events, self.window_s, self._clock = max_events, window_s, clock
        self._events: deque[float] = deque()

    def _trim(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.window_s:
            self._events.popleft()

    def allow(self) -> bool:
        """Record one event and return True if it is within the limit; a blocked call is not recorded."""
        now = self._clock()
        self._trim(now)
        if len(self._events) >= self.max_events:
            return False
        self._events.append(now)
        return True

    def retry_after(self) -> float:
        """Seconds until the next call would be allowed (0 when allowed now)."""
        now = self._clock()
        self._trim(now)
        if len(self._events) < self.max_events:
            return 0.0
        return max(0.0, self.window_s - (now - self._events[0]))


MAX_CHAT_CHARS = 500


def clean_chat_input(text: str, limit: int = MAX_CHAT_CHARS) -> str:
    """Trim whitespace, drop control characters and cap the length of a chat message."""
    cleaned = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    return cleaned.strip()[:limit]
