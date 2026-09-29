"""In-memory sliding-window rate limiting, per endpoint bucket (Security §07).

Limits are applied per identity (session token) with separate buckets for
upload, chat, and status endpoints. Single-process only for the MVP —
documented in docs/DECISIONS.md #16; swap for a shared store when scaling out.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import AppError, ErrorCode


class RateLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> None:
        """Raise 429 RATE_LIMITED when `limit` was already reached in the window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                raise AppError(ErrorCode.RATE_LIMITED)
            bucket.append(now)

    def _reset_for_tests(self) -> None:
        with self._lock:
            self._events.clear()
