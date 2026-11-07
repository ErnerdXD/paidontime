"""Small in-memory rate limiter and daily budget for the public demo.

Render's free tier runs one instance, so process memory is enough here. If the
app is ever scaled horizontally, move these counters to Redis or Postgres.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date


class Limiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._daily: dict[str, dict] = {}

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        daily_key: str | None = None,
        daily_limit: int = 0,
    ) -> tuple[bool, int]:
        """Record one hit. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            events = self._events[key]
            while events and events[0] < now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                retry = max(1, int(window_seconds - (now - events[0])))
                return False, retry

            if daily_key and daily_limit:
                today = date.today().isoformat()
                bucket = self._daily.get(daily_key)
                if not bucket or bucket["date"] != today:
                    bucket = {"date": today, "count": 0}
                if bucket["count"] >= daily_limit:
                    return False, 3600
                bucket["count"] += 1
                self._daily[daily_key] = bucket

            events.append(now)
            return True, 0


LIMITER = Limiter()
