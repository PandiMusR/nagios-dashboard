from __future__ import annotations

import subprocess
import threading
import time
from typing import Any


class DockerCache:
    """In-memory cache for Docker CLI results with TTL.

    Reduces overhead from repeated `docker ps`, `docker port`, `docker stats`
    calls that happen on every HTTP request. Results are cached for `ttl`
    seconds and refreshed automatically on the next access after expiry.
    """

    def __init__(self, ttl: int = 15) -> None:
        self._ttl = ttl
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return cached value if still valid, otherwise None."""
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() < entry['expires']:
                return entry['value']
        return None

    def set(self, key: str, value: Any) -> None:
        """Store a value in cache with TTL."""
        with self._lock:
            self._cache[key] = {
                'value': value,
                'expires': time.time() + self._ttl,
            }

    def get_or_run(self, key: str, cmd: list[str], timeout: int = 5) -> str:
        """Return cached output for `cmd`, or run it and cache the result.

        Only caches successful results (returncode 0). Failed commands
        are not cached so subsequent calls can retry.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return result.stdout
        output = result.stdout
        self.set(key, output)
        return output

    def invalidate(self, key: str | None = None) -> None:
        """Remove one or all entries from cache."""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()


# Global singleton — 15 second TTL
docker_cache = DockerCache(ttl=15)
