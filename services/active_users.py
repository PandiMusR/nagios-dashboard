from __future__ import annotations

import threading
import time
from datetime import datetime


class ActiveUsersTracker:
    """In-memory tracker for active user sessions.

    Tracks last activity timestamp per user. Users are considered
    "active" if they have made a request within the idle threshold.
    Auto-refresh requests (e.g. monitoring data fetch) count as activity
    so users viewing the monitoring page stay marked as active.
    """

    def __init__(self, idle_timeout_seconds: int = 300) -> None:
        self._users: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._idle_timeout = idle_timeout_seconds

        # Background cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def update(self, username: str, ip: str, role: str) -> None:
        """Record activity for a user. Called on every authenticated request."""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._lock:
            if username not in self._users:
                self._users[username] = {
                    'username': username,
                    'ip': ip,
                    'role': role,
                    'login_at': now,
                    'last_active': now,
                }
            else:
                self._users[username]['last_active'] = now
                self._users[username]['ip'] = ip
                self._users[username]['role'] = role

    def remove(self, username: str) -> None:
        """Remove user from tracking (called on logout)."""
        with self._lock:
            self._users.pop(username, None)

    def get_active_users(self) -> list[dict]:
        """Return list of currently active users."""
        now = time.time()
        cutoff = now - self._idle_timeout
        result = []
        with self._lock:
            for user in self._users.values():
                last_active = datetime.strptime(user['last_active'], '%Y-%m-%d %H:%M:%S')
                idle_seconds = now - last_active.timestamp()
                if idle_seconds < self._idle_timeout:
                    entry = dict(user)
                    entry['idle_seconds'] = int(idle_seconds)
                    if idle_seconds < 60:
                        entry['idle_str'] = f'{int(idle_seconds)}s'
                    elif idle_seconds < 3600:
                        entry['idle_str'] = f'{int(idle_seconds // 60)}m {int(idle_seconds % 60)}s'
                    else:
                        entry['idle_str'] = f'{int(idle_seconds // 3600)}h {int((idle_seconds % 3600) // 60)}m'
                    result.append(entry)
        result.sort(key=lambda x: x['idle_seconds'])
        return result

    def get_count(self) -> int:
        """Return count of active users."""
        return len(self.get_active_users())

    def _cleanup_loop(self) -> None:
        """Background thread: remove idle users every 60 seconds."""
        while True:
            time.sleep(60)
            now = time.time()
            cutoff = now - self._idle_timeout
            with self._lock:
                stale = [
                    username for username, data in self._users.items()
                    if datetime.strptime(data['last_active'], '%Y-%m-%d %H:%M:%S').timestamp() < cutoff
                ]
                for username in stale:
                    del self._users[username]


# Global singleton
active_users = ActiveUsersTracker(idle_timeout_seconds=300)
