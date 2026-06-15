"""Tests for the CircuitBreaker class and worker circuit breaker integration."""

import time
from unittest.mock import AsyncMock

import pytest

from src.core.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreakerInitialState:
    """Test that the CircuitBreaker starts in the correct initial state."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_zero(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.failure_count == 0

    def test_initial_no_last_failure_time(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.time_since_last_failure() == float("inf")

    def test_custom_thresholds(self):
        cb = CircuitBreaker(failure_threshold=7, recovery_timeout=120.0)
        assert cb.failure_threshold == 7
        assert cb.recovery_timeout == 120.0


class TestCircuitBreakerSuccess:
    """Test that success resets the failure count."""

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_success_transitions_open_to_closed(self):
        """Success in OPEN state transitions to CLOSED (standard circuit breaker behavior)."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_multiple_successes_reset(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        for _ in range(5):
            cb.record_failure()
            cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerFailure:
    """Test that failures increment the count and can open the circuit."""

    def test_single_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED
        # Verify last failure time is recorded
        assert cb.time_since_last_failure() < float("inf")

    def test_failure_at_threshold_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Verify last failure time is set
        assert cb.time_since_last_failure() < float("inf")

    def test_failure_beyond_threshold_stays_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_failure_after_open_does_not_affect_state(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerRecovery:
    """Test the transition from OPEN to HALF_OPEN to CLOSED."""

    def test_recovery_timeout_allows_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Check state - should transition to half_open
        # The state check should trigger the transition
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_checks_are_sequential(self):
        """Test that multiple half_open checks only transition once."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.1)

        # Multiple checks should all return HALF_OPEN
        state1 = cb.state
        state2 = cb.state
        state3 = cb.state
        assert state1 == CircuitState.HALF_OPEN
        assert state2 == CircuitState.HALF_OPEN
        assert state3 == CircuitState.HALF_OPEN


class TestCircuitBreakerIsAvailable:
    """Test the allow_request method (equivalent of is_available)."""

    def test_available_in_closed_state(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.allow_request() is True

    def test_unavailable_in_open_state(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is False

    def test_available_in_half_open_state(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.1)
        # In half_open state, allow_request allows one probe
        assert cb.allow_request() is True


class TestCircuitBreakerReset:
    """Test the reset method."""

    def test_reset_clears_state(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.time_since_last_failure() == float("inf")


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_failure_threshold(self):
        """A threshold of 0 means the circuit opens immediately on first failure."""
        cb = CircuitBreaker(failure_threshold=0, recovery_timeout=10.0)
        cb.record_failure()
        # With threshold=0, the circuit should open
        assert cb.state == CircuitState.OPEN

    def test_recovery_timeout_zero(self):
        """A recovery timeout of 0 allows immediate transition to half_open."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.0)
        cb.record_failure()
        cb.record_failure()
        # With timeout=0, the state getter immediately transitions to half_open
        assert cb.state == CircuitState.HALF_OPEN

    def test_rapid_failures_and_successes(self):
        """Test many rapid failures and successes."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=0.1)

        # Build up failures
        for i in range(5):
            cb.record_failure()
            if i < 4:
                assert cb.state == CircuitState.CLOSED
            else:
                assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

        # Repeat
        for i in range(5):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN


class TestWorkerCircuitBreakerIntegration:
    """Test that workers correctly use circuit breakers."""

    @pytest.mark.asyncio
    async def test_worker_has_circuit_breaker(self):
        """Worker instances should have a circuit breaker attribute."""
        from src.web.main import Worker

        mock_ws = AsyncMock()
        worker = Worker("test-id", "test-worker", mock_ws)
        assert hasattr(worker, "circuit_breaker")
        assert isinstance(worker.circuit_breaker, CircuitBreaker)

    @pytest.mark.asyncio
    async def test_worker_is_unavailable_when_circuit_open(self):
        """Worker should be unavailable when circuit breaker is open."""
        from src.web.main import Worker

        mock_ws = AsyncMock()
        worker = Worker("test-id", "test-worker", mock_ws)

        # Fill up the circuit breaker
        for _ in range(5):
            worker.mark_connection_failure()

        assert worker.is_unavailable is True
        assert worker.status == "Unavailable"

    @pytest.mark.asyncio
    async def test_worker_available_after_success(self):
        """Worker should become available after a successful ping."""
        from src.web.main import Worker

        mock_ws = AsyncMock()
        worker = Worker("test-id", "test-worker", mock_ws)

        # Open the circuit
        worker.circuit_breaker.failure_threshold = 2
        worker.mark_connection_failure()
        worker.mark_connection_failure()
        assert worker.is_unavailable is True

        # Reset for success test
        worker.circuit_breaker.reset()
        worker.status = "Idle"

        # Record a success
        worker.mark_connection_success()
        assert worker.is_unavailable is False

    @pytest.mark.asyncio
    async def test_worker_mark_connection_failure_sets_unavailable(self):
        """mark_connection_failure should set status to Unavailable."""
        from src.web.main import Worker

        mock_ws = AsyncMock()
        worker = Worker("test-id", "test-worker", mock_ws)
        worker.status = "Idle"
        worker.circuit_breaker.failure_threshold = 1

        worker.mark_connection_failure()
        assert worker.status == "Unavailable"


class TestWorkerManagerPingWorker:
    """Test the WorkerManager.ping_worker method."""

    @pytest.mark.asyncio
    async def test_ping_worker_success(self):
        """Successful ping should reset circuit breaker."""
        from src.web.main import Worker, WorkerManager

        manager = WorkerManager()
        mock_ws = AsyncMock()
        worker = Worker("test-id", "test-worker", mock_ws)
        worker.circuit_breaker.failure_threshold = 1
        worker.mark_connection_failure()  # Open the circuit

        manager.active_workers["test-id"] = worker
        mock_ws.send_json = AsyncMock()

        result = await manager.ping_worker("test-id")
        assert result is True
        assert worker.is_unavailable is False

    @pytest.mark.asyncio
    async def test_ping_worker_connection_error(self):
        """Failed ping should record failure on circuit breaker."""
        from src.web.main import Worker, WorkerManager

        manager = WorkerManager()
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("connection lost"))
        worker = Worker("test-id", "test-worker", mock_ws)
        worker.circuit_breaker.failure_threshold = 2
        manager.active_workers["test-id"] = worker

        result = await manager.ping_worker("test-id")
        assert result is False
        assert worker.circuit_breaker.failure_count >= 1

    @pytest.mark.asyncio
    async def test_ping_worker_unknown_id(self):
        """Ping to unknown worker should return False."""
        from src.web.main import WorkerManager

        manager = WorkerManager()
        result = await manager.ping_worker("nonexistent")
        assert result is False
