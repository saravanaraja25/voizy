"""Sliding-window failure throttle for login and other unauthenticated endpoints.

In-memory and per process: right for a single self-hosted instance. A multi-instance deployment
should put a shared limiter (reverse proxy or Redis) in front; this is the safety net, not the plan.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class Throttle:
    def __init__(
        self,
        max_failures: int,
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        self._max = max_failures
        self._window = window_s
        self._clock = clock
        self._max_keys = max_keys
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._events[key]
        while q and now - q[0] > self._window:
            q.popleft()
        if not q:
            self._events.pop(key, None)
        return q

    def retry_after(self, key: str) -> float:
        """Seconds until another attempt is allowed; 0 when the key may proceed."""
        with self._lock:
            now = self._clock()
            q = self._prune(key, now)
            if len(q) < self._max:
                return 0.0
            return max(0.0, self._window - (now - q[0]))

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            if key not in self._events and len(self._events) >= self._max_keys:
                # Bound memory under a flood of distinct keys: drop the oldest-touched key.
                self._events.pop(next(iter(self._events)))
            self._prune(key, now)
            self._events[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
