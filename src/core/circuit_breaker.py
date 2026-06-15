"""Circuit breaker pattern for resilient connections.

Implements the classic three-state circuit breaker:
  CLOSED   → normal operation, failures counted
  OPEN     → connections rejected, waits for recovery timeout
  HALF_OPEN → one probe allowed, success → CLOSED, failure → OPEN
"""

import time
from enum import Enum
from typing import Any, Callable


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Raised when a circuit is open and the call is rejected."""

    def __init__(self, state: CircuitState, failures: int, last_failure_time: float):
        self.state = state
        self.failures = failures
        self.last_failure_time = last_failure_time
        super().__init__(
            f"Circuit breaker is {state.value} "
            f"(failures={failures}, last_failure={last_failure_time:.1f}s ago)"
        )


class CircuitBreaker:
    """A circuit breaker that wraps async callable calls.

    Parameters
    ----------
    failure_threshold : int
        Number of consecutive failures before opening the circuit.
    recovery_timeout : float
        Seconds to wait in OPEN state before transitioning to HALF_OPEN.
    half_open_max_calls : int
        Maximum concurrent calls allowed in HALF_OPEN state.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._opened_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def state(self) -> CircuitState:
        """Return the current state, auto-transitioning from OPEN → HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    def record_success(self) -> None:
        """Record a successful call — transitions OPEN/HALF_OPEN → CLOSED."""
        if self._state != CircuitState.CLOSED:
            self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        """Record a failed call — may transition to OPEN."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN immediately re-opens
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            self._half_open_calls = 0
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()

    def allow_request(self) -> bool:
        """Check whether a call is allowed (respects HALF_OPEN concurrency)."""
        current = self.state  # may auto-transition OPEN → HALF_OPEN
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False  # OPEN

    def enter_half_open(self) -> None:
        """Force transition to HALF_OPEN (useful for testing / manual probe)."""
        if self._state == CircuitState.OPEN:
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._opened_at = time.time()

    def time_since_last_failure(self) -> float:
        """Seconds elapsed since the last recorded failure."""
        if self._last_failure_time == 0.0:
            return float("inf")
        return time.time() - self._last_failure_time

    # ------------------------------------------------------------------
    # Decorator-style usage
    # ------------------------------------------------------------------
    async def call(self, func: Callable, *args: Any, **kwargs: Any):
        """Execute *func* through the circuit breaker.

        Raises ``CircuitBreakerError`` when the circuit is OPEN or
        HALF_OPEN with no available slots.
        """
        if not self.allow_request():
            raise CircuitBreakerError(
                self.state, self._failure_count, self._last_failure_time
            )

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self.state.value}, "
            f"failures={self._failure_count}, "
            f"threshold={self.failure_threshold})"
        )


# ------------------------------------------------------------------
# Simple convenience function for one-shot calls
# ------------------------------------------------------------------
async def circuit_breaking_call(
    func: Callable,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    *args: Any,
    **kwargs: Any,
):
    """One-shot wrapper around :class:`CircuitBreaker`.

    Creates a fresh breaker, executes *func*, and returns the result.
    Useful for non-stateful contexts (e.g. ad-hoc HTTP calls).
    """
    cb = CircuitBreaker(
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )
    return await cb.call(func, *args, **kwargs)
