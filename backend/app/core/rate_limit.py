"""Per-client fixed-window rate limiting for public endpoints.

v1 has no authentication, so the public endpoints are protected by a per-IP request
budget. The limiter is deliberately small and dependency-free: it is a fixed-window
counter with an injectable clock, which makes it directly unit-testable without
sleeping in tests.

Scope: state is held in this process's memory. Running several backend replicas
therefore gives each replica its own budget. That is acceptable for v1 and is
recorded in the README's "Known limitations"; a shared Redis backend is the upgrade
path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from app.core.constants import RATE_LIMIT_PRUNE_INTERVAL_SECONDS


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The outcome of a rate-limit check.

    Attributes:
        allowed: Whether the request may proceed.
        remaining: Requests left in the current window, never negative.
        retry_after_seconds: Whole seconds until the window resets. Sent as the
            ``Retry-After`` header when the request is rejected.
        limit: The configured budget, echoed for the response headers.
    """

    allowed: bool
    remaining: int
    retry_after_seconds: int
    limit: int


@dataclass
class _Window:
    """Mutable per-client counter state."""

    count: int
    started_at: float


class FixedWindowRateLimiter:
    """Counts requests per client within a fixed time window.

    A fixed window can admit up to twice the budget across a window boundary. That
    is a known and accepted property: the goal here is to bound abuse of the free
    third-party quotas behind this API, not to enforce a precise contractual rate.
    A sliding-window counter would cost more memory for accuracy this does not need.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a limiter.

        Args:
            max_requests: Requests permitted per window per client.
            window_seconds: Window length in seconds.
            clock: Monotonic time source. Injectable so tests control time directly.

        Raises:
            ValueError: If the budget or window is not positive.
        """
        if max_requests < 1:
            raise ValueError(f"max_requests must be at least 1, got {max_requests}")
        if window_seconds < 1:
            raise ValueError(f"window_seconds must be at least 1, got {window_seconds}")

        self._max_requests = max_requests
        self._window_seconds = float(window_seconds)
        self._clock = clock
        self._windows: dict[str, _Window] = {}
        # Guards `_windows`. Starlette runs middleware on the event loop, but
        # sync endpoints execute in a thread pool, so the state can be reached
        # from more than one thread.
        self._lock = Lock()
        self._last_pruned_at = clock()

    def check(self, client_key: str) -> RateLimitDecision:
        """Record a request from ``client_key`` and decide whether it may proceed.

        Args:
            client_key: Stable per-client identifier, normally the remote IP.
        """
        now = self._clock()

        with self._lock:
            self._prune_expired(now)

            window = self._windows.get(client_key)
            if window is None or now - window.started_at >= self._window_seconds:
                window = _Window(count=0, started_at=now)
                self._windows[client_key] = window

            window.count += 1
            count = window.count
            elapsed = now - window.started_at

        allowed = count <= self._max_requests
        remaining = max(0, self._max_requests - count)
        retry_after = 0 if allowed else max(1, int(self._window_seconds - elapsed) + 1)

        return RateLimitDecision(
            allowed=allowed,
            remaining=remaining,
            retry_after_seconds=retry_after,
            limit=self._max_requests,
        )

    def _prune_expired(self, now: float) -> None:
        """Drop windows that have expired.

        Without this the map grows without bound, one entry per IP ever seen.
        Pruning is throttled so a burst of requests does not rescan the map each
        time. Callers must hold the lock.
        """
        if now - self._last_pruned_at < RATE_LIMIT_PRUNE_INTERVAL_SECONDS:
            return
        cutoff = now - self._window_seconds
        expired = [key for key, window in self._windows.items() if window.started_at < cutoff]
        for key in expired:
            del self._windows[key]
        self._last_pruned_at = now

    def reset(self) -> None:
        """Discard all counters. Used between tests."""
        with self._lock:
            self._windows.clear()
