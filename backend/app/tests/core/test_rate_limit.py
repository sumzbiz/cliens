"""Tests for the per-IP rate limiter.

The clock is injected, so window expiry is tested by advancing a variable rather
than sleeping — the suite stays fast and has no timing flakiness.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import FixedWindowRateLimiter


class FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestConstruction:
    """Invalid configuration must fail at construction, not at the first request."""

    @pytest.mark.parametrize("max_requests", [0, -1])
    def test_rejects_non_positive_budget(self, max_requests: int) -> None:
        with pytest.raises(ValueError, match="max_requests must be at least 1"):
            FixedWindowRateLimiter(max_requests=max_requests, window_seconds=60)

    @pytest.mark.parametrize("window_seconds", [0, -5])
    def test_rejects_non_positive_window(self, window_seconds: int) -> None:
        with pytest.raises(ValueError, match="window_seconds must be at least 1"):
            FixedWindowRateLimiter(max_requests=10, window_seconds=window_seconds)


class TestBudgetEnforcement:
    """The budget is what protects the free third-party quotas behind this API."""

    def test_allows_requests_up_to_the_budget(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=3, window_seconds=60, clock=FakeClock())
        assert [limiter.check("1.2.3.4").allowed for _ in range(3)] == [True, True, True]

    def test_rejects_the_request_after_the_budget(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=3, window_seconds=60, clock=FakeClock())
        for _ in range(3):
            limiter.check("1.2.3.4")
        assert not limiter.check("1.2.3.4").allowed

    def test_remaining_counts_down_and_never_goes_negative(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60, clock=FakeClock())
        assert limiter.check("1.2.3.4").remaining == 1
        assert limiter.check("1.2.3.4").remaining == 0
        assert limiter.check("1.2.3.4").remaining == 0
        assert limiter.check("1.2.3.4").remaining == 0

    def test_reports_the_configured_limit(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=7, window_seconds=60, clock=FakeClock())
        assert limiter.check("1.2.3.4").limit == 7


class TestClientIsolation:
    """One noisy client must not consume another client's budget."""

    def test_clients_have_independent_budgets(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60, clock=FakeClock())
        limiter.check("1.1.1.1")
        limiter.check("1.1.1.1")

        assert not limiter.check("1.1.1.1").allowed
        assert limiter.check("2.2.2.2").allowed


class TestWindowExpiry:
    """A client must regain its budget once the window rolls over."""

    def test_budget_resets_after_the_window(self) -> None:
        clock = FakeClock()
        limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        assert not limiter.check("1.2.3.4").allowed

        clock.advance(60.0)
        assert limiter.check("1.2.3.4").allowed

    def test_budget_does_not_reset_before_the_window_ends(self) -> None:
        clock = FakeClock()
        limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")

        clock.advance(59.0)
        assert not limiter.check("1.2.3.4").allowed

    def test_retry_after_is_positive_when_rejected(self) -> None:
        """Clients need an actionable Retry-After, never zero."""
        clock = FakeClock()
        limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60, clock=clock)
        limiter.check("1.2.3.4")

        clock.advance(30.0)
        decision = limiter.check("1.2.3.4")
        assert not decision.allowed
        assert decision.retry_after_seconds >= 1

    def test_retry_after_is_zero_when_allowed(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=5, window_seconds=60, clock=FakeClock())
        assert limiter.check("1.2.3.4").retry_after_seconds == 0


class TestMemoryManagement:
    """Without pruning the map grows by one entry per IP ever seen."""

    def test_expired_windows_are_eventually_pruned(self) -> None:
        clock = FakeClock()
        limiter = FixedWindowRateLimiter(max_requests=5, window_seconds=10, clock=clock)
        for octet in range(50):
            limiter.check(f"10.0.0.{octet}")

        # Advance past both the window and the prune interval, then touch the
        # limiter so a sweep runs.
        clock.advance(1_000.0)
        limiter.check("192.168.0.1")

        # Reaching into private state is deliberate: pruning has no public
        # observable effect other than memory, which is exactly the contract here.
        assert len(limiter._windows) == 1

    def test_reset_clears_all_counters(self) -> None:
        limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=60, clock=FakeClock())
        limiter.check("1.2.3.4")
        assert not limiter.check("1.2.3.4").allowed

        limiter.reset()
        assert limiter.check("1.2.3.4").allowed
