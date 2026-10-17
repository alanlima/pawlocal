from collections import defaultdict, deque
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException

from pawlocal.config import settings


class InMemoryWriteRateLimiter:
    """Per-process write limit for this single-instance local MVP API."""

    def __init__(self):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def check(self, subject: str, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        cutoff = current - 60
        with self._lock:
            events = self._events[subject]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= settings.write_rate_limit_per_minute:
                retry_after = max(1, ceil(60 - (current - events[0])))
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "rate_limited",
                        "message": "Request rate limit exceeded",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(current)


write_rate_limiter = InMemoryWriteRateLimiter()


def enforce_write_rate_limit(subject: str) -> None:
    write_rate_limiter.check(subject)
