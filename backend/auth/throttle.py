"""Process-local login throttling and token revocation. Limitation: state is per API process and is lost on restart;
fine for a single-instance prototype, use a shared store (database/Redis) when running several instances."""
from __future__ import annotations

import threading
import time


class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300, clock=time.monotonic):
        self.max_failures, self.window, self.clock = max_failures, window_seconds, clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = self.clock() - self.window
        self._fails[key] = [t for t in self._fails.get(key, []) if t > cutoff]
        return self._fails[key]

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key.lower())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key.lower()).append(self.clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key.lower(), None)


class RevokedTokens:
    def __init__(self, clock=time.time):
        self.clock, self._items, self._lock = clock, {}, threading.Lock()

    def revoke(self, jti: str, exp: float) -> None:
        with self._lock:
            self._items[jti] = exp
            now = self.clock()
            for k in [k for k, v in self._items.items() if v < now]:
                del self._items[k]

    def is_revoked(self, jti: str | None) -> bool:
        return bool(jti) and jti in self._items
