"""Unit tests for tool executor - PR-3.

Tests cover:
1. Timeout behavior
2. Retry + jitter
3. Circuit breaker (5 failures, half-open, cancellations don't count)
4. Cache integration
5. Cancellation (before execute, between attempts)
6. Metrics wiring
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY
from pydantic import BaseModel

from backend.app.tools.executor import (
    BreakerState,
    CancelToken,
    CircuitBreaker,
    ToolCache,
    ToolCancelledError,
    ToolCircuitOpenError,
    ToolConfig,
    ToolContext,
    ToolExecutor,
    ToolResult,
    ToolTimeoutError,
    get_breaker_registry,
)
from backend.app.utils.metrics import PrometheusToolMetrics


class DummyPayload(BaseModel):
    """Test payload."""

    value: str


class TestCancelToken:
    """Test CancelToken behavior."""

    def test_cancel_token_not_cancelled_by_default(self) -> None:
        token = CancelToken()
        assert token.cancelled is False
        token.throw_if_cancelled()  # Should not raise

    def test_cancel_token_throws_when_cancelled(self) -> None:
        token = CancelToken(cancelled=True)
        with pytest.raises(ToolCancelledError, match="run cancelled"):
            token.throw_if_cancelled()


class TestCircuitBreaker:
    """Test CircuitBreaker state transitions."""

    def test_breaker_starts_closed(self) -> None:
        breaker = CircuitBreaker(
            tool_name="test",
            failure_threshold=5,
            window_seconds=60,
            half_open_seconds=30,
        )
        assert breaker.state == BreakerState.CLOSED

    def test_breaker_opens_after_threshold_failures(self) -> None:
        now = datetime.now()
        breaker = CircuitBreaker(
            tool_name="test",
            failure_threshold=3,
            window_seconds=60,
            half_open_seconds=30,
        )

        # Record 3 failures
        for _ in range(3):
            breaker.record_failure(now)

        state = breaker.check_and_update_state(now)
        assert state == BreakerState.OPEN

    def test_breaker_cleans_old_failures_outside_window(self) -> None:
        now = datetime.now()
        breaker = CircuitBreaker(
            tool_name="test",
            failure_threshold=3,
            window_seconds=60,
            half_open_seconds=30,
        )

        # Record 2 old failures
        old_time = now - timedelta(seconds=65)
        breaker.record_failure(old_time)
        breaker.record_failure(old_time)

        # Record 1 recent failure
        breaker.record_failure(now)

        # Should still be closed (old failures don't count)
        state = breaker.check_and_update_state(now)
        assert state == BreakerState.CLOSED
        assert len(breaker.failure_times) == 1

    def test_breaker_transitions_to_half_open(self) -> None:
        now = datetime.now()
        breaker = CircuitBreaker(
            tool_name="test",
            failure_threshold=2,
            window_seconds=60,
            half_open_seconds=30,
        )

        # Open the breaker
        breaker.record_failure(now)
        breaker.record_failure(now)
        assert breaker.check_and_update_state(now) == BreakerState.OPEN

        # Wait for half_open_seconds
        later = now + timedelta(seconds=31)
        state = breaker.check_and_update_state(later)
        assert state == BreakerState.HALF_OPEN

    def test_breaker_record_success_closes_from_half_open(self) -> None:
        now = datetime.now()
        breaker = CircuitBreaker(
            tool_name="test",
            failure_threshold=2,
            window_seconds=60,
            half_open_seconds=30,
        )

        # Open the breaker
        breaker.record_failure(now)
        breaker.record_failure(now)
        breaker.check_and_update_state(now)

        # Transition to half-open
        later = now + timedelta(seconds=31)
        breaker.check_and_update_state(later)
        assert breaker.state == BreakerState.HALF_OPEN

        # Success closes it
        breaker.record_success()
        assert breaker.state == BreakerState.CLOSED
        assert len(breaker.failure_times) == 0


class TestToolCache:
    """Test ToolCache behavior."""

    def test_cache_makes_deterministic_keys(self) -> None:
        cache = ToolCache()
        payload1 = DummyPayload(value="test")
        payload2 = DummyPayload(value="test")

        key1 = cache.make_key("weather", payload1)
        key2 = cache.make_key("weather", payload2)

        assert key1 == key2

    def test_cache_different_payloads_different_keys(self) -> None:
        cache = ToolCache()
        payload1 = DummyPayload(value="test1")
        payload2 = DummyPayload(value="test2")

        key1 = cache.make_key("weather", payload1)
        key2 = cache.make_key("weather", payload2)

        assert key1 != key2

    def test_cache_get_returns_none_when_empty(self) -> None:
        from datetime import datetime

        cache = ToolCache()
        payload = DummyPayload(value="test")
        key = cache.make_key("weather", payload)
        result = cache.get(key, datetime.now())
        assert result is None

    def test_cache_get_returns_value_when_present_and_not_expired(self) -> None:
        from datetime import datetime

        cache = ToolCache()
        payload = DummyPayload(value="test")
        key = cache.make_key("weather", payload)
        cache.set(key, {"temp": 72}, ttl_seconds=60, now=datetime.now())

        result = cache.get(key, datetime.now())
        assert result == {"temp": 72}

    def test_cache_get_returns_none_when_expired(self) -> None:
        from datetime import datetime

        cache = ToolCache()
        payload = DummyPayload(value="test")
        key = cache.make_key("weather", payload)

        # Set with 0 TTL (instantly expired)
        cache.set(key, {"temp": 72}, ttl_seconds=0, now=datetime.now())

        result = cache.get(key, datetime.now())
        assert result is None


class TestToolExecutor:
    """Test ToolExecutor execution logic."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        """Test basic successful tool execution."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        async def dummy_tool(payload: DummyPayload) -> dict[str, Any]:
            return {"result": payload.value}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="dummy")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=1,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
        )
        payload = DummyPayload(value="test")

        result = await executor.execute(ctx, config, dummy_tool, payload)
        assert result.value == {"result": "test"}
        assert result.provenance.source == "tool"
        assert result.provenance.cache_hit is False

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self) -> None:
        """Test that exceeding hard timeout raises ToolTimeoutError."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        async def slow_tool(payload: DummyPayload) -> dict[str, Any]:
            await asyncio.sleep(10)  # Much longer than hard timeout
            return {"result": "too slow"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="slow")
        config = ToolConfig(
            soft_timeout_ms=100,
            hard_timeout_ms=200,
            retry_count=1,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        with pytest.raises(ToolTimeoutError):
            await executor.execute(ctx, config, slow_tool, payload)

    @pytest.mark.asyncio
    async def test_retry_with_jitter(self) -> None:
        """Test retry logic with jitter between attempts."""
        metrics = PrometheusToolMetrics()
        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        executor = ToolExecutor(metrics=metrics, sleep_fn=fake_sleep)

        call_count = 0

        async def flaky_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first attempt fails")
            return {"result": "success"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="flaky")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=1,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        result = await executor.execute(ctx, config, flaky_tool, payload)
        assert result.value == {"result": "success"}
        assert call_count == 2

        # Verify jitter was applied
        assert len(sleep_calls) == 1
        jitter_seconds = sleep_calls[0]
        assert 0.2 <= jitter_seconds <= 0.5

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self) -> None:
        """Test circuit breaker opens after threshold failures."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        async def always_fails(payload: DummyPayload) -> dict[str, Any]:
            raise Exception("always fails")

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="breaker_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,  # No retries
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            breaker_failure_threshold=3,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        # First 3 attempts should fail with execution error
        from backend.app.tools.executor import ToolExecutionError

        for _ in range(3):
            with pytest.raises(ToolExecutionError):
                await executor.execute(ctx, config, always_fails, payload)

        # 4th attempt should fail with circuit open
        with pytest.raises(ToolCircuitOpenError):
            await executor.execute(ctx, config, always_fails, payload)

    @pytest.mark.asyncio
    async def test_circuit_breaker_cancellations_dont_count(self) -> None:
        """Test that cancellations don't increment breaker failure count."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        async def dummy_tool(payload: DummyPayload) -> dict[str, Any]:
            return {"result": "ok"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cancel_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            breaker_failure_threshold=2,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")
        cancel_token = CancelToken(cancelled=True)

        # 5 cancelled attempts
        for _ in range(5):
            with pytest.raises(ToolCancelledError):
                await executor.execute(ctx, config, dummy_tool, payload, cancel_token)

        # Should still be able to execute (breaker not open)
        normal_token = CancelToken(cancelled=False)
        result = await executor.execute(ctx, config, dummy_tool, payload, normal_token)
        assert result.value == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_cache_integration(self) -> None:
        """Test cache integration: first call executes, second hits cache."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0

        async def counted_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"result": f"call_{call_count}"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cached")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=3600,  # 1 hour TTL
        )
        payload = DummyPayload(value="test")

        # Use a shared cache instance for both calls
        cache = ToolCache()

        # First call should execute
        result1 = await executor.execute(ctx, config, counted_tool, payload, cache=cache)
        assert result1.value == {"result": "call_1"}
        assert result1.provenance.cache_hit is False
        assert call_count == 1

        # Second call should hit cache
        result2 = await executor.execute(ctx, config, counted_tool, payload, cache=cache)
        assert result2.value == {"result": "call_1"}  # Same result
        assert result2.provenance.cache_hit is True  # Provenance indicates cache hit
        assert call_count == 1  # Tool not called again

    @pytest.mark.asyncio
    async def test_cancellation_before_execute(self) -> None:
        """Test cancellation before execution prevents tool from running."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        tool_called = False

        async def dummy_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal tool_called
            tool_called = True
            return {"result": "ok"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cancel_before")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
        )
        payload = DummyPayload(value="test")
        cancel_token = CancelToken(cancelled=True)

        with pytest.raises(ToolCancelledError):
            await executor.execute(ctx, config, dummy_tool, payload, cancel_token)

        assert tool_called is False

    @pytest.mark.asyncio
    async def test_cancellation_between_attempts(self) -> None:
        """Test cancellation between retry attempts."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0
        cancel_token = CancelToken(cancelled=False)

        async def flaky_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Cancel after first attempt
                cancel_token.cancelled = True
                raise Exception("first attempt fails")
            return {"result": "should not get here"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cancel_between")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=2,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        with pytest.raises(ToolCancelledError):
            await executor.execute(ctx, config, flaky_tool, payload, cancel_token)

        # Should have been called only once
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_metrics_recorded(self) -> None:
        """Test that metrics are properly recorded with correct labels and values."""
        from backend.app.utils.metrics import (
            tool_cache_hits_total,
            tool_errors_total,
            tool_latency_ms,
        )

        # Register metrics if not already registered
        try:
            REGISTRY.register(tool_latency_ms)
        except Exception:
            pass
        try:
            REGISTRY.register(tool_errors_total)
        except Exception:
            pass
        try:
            REGISTRY.register(tool_cache_hits_total)
        except Exception:
            pass

        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        # === Test 1: Success outcome ===
        async def success_tool(payload: DummyPayload) -> dict[str, Any]:
            return {"result": "ok"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="metric_success")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        await executor.execute(ctx, config, success_tool, payload)

        # === Test 2: Cache hit outcome ===
        cache = ToolCache()
        ctx_cache = ToolContext(trace_id="tr2", run_id="run2", tool_name="metric_cache")
        config_cache = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=3600,
        )

        # First call to populate cache
        await executor.execute(ctx_cache, config_cache, success_tool, payload, cache=cache)
        # Second call hits cache
        await executor.execute(ctx_cache, config_cache, success_tool, payload, cache=cache)

        # === Test 3: Timeout outcome ===
        async def timeout_tool(payload: DummyPayload) -> dict[str, Any]:
            await asyncio.sleep(10)
            return {"result": "timeout"}

        ctx_timeout = ToolContext(trace_id="tr3", run_id="run3", tool_name="metric_timeout")
        config_timeout = ToolConfig(
            soft_timeout_ms=100,
            hard_timeout_ms=200,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )

        try:
            await executor.execute(ctx_timeout, config_timeout, timeout_tool, payload)
        except ToolTimeoutError:
            pass  # Expected

        # Verify metrics were recorded with correct labels
        from prometheus_client import generate_latest

        metrics_output = generate_latest().decode("utf-8")

        # Check histogram presence
        assert "tool_latency_ms" in metrics_output

        # Verify success outcome labels
        assert 'tool="metric_success"' in metrics_output
        assert 'outcome="success"' in metrics_output

        # Verify cache hit outcome labels
        assert 'tool="metric_cache"' in metrics_output
        assert 'outcome="cache_hit"' in metrics_output

        # Verify error counters
        assert "tool_errors_total" in metrics_output
        assert 'tool="metric_timeout"' in metrics_output
        assert 'reason="timeout"' in metrics_output

        # Verify cache hit counter
        assert "tool_cache_hits_total" in metrics_output

    @pytest.mark.asyncio
    async def test_shared_breaker_opens_across_multiple_calls(self) -> None:
        """Test that circuit breaker state is shared across multiple execute() calls.

        This verifies SPEC §4.2 requirement that breaker state persists across
        executor invocations for the same tool.
        """
        # Clear registry to ensure clean state
        registry = get_breaker_registry()
        registry.clear()

        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0

        async def always_fails(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            raise Exception("persistent failure")

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="shared_breaker_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,  # No retries
            retry_jitter_min_ms=0,
            retry_jitter_max_ms=0,
            breaker_failure_threshold=3,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        # First 3 calls should execute and fail with normal exception
        for i in range(3):
            from backend.app.tools.executor import ToolExecutionError
            with pytest.raises(ToolExecutionError):
                await executor.execute(ctx, config, always_fails, payload)

        # Verify 3 calls were made
        assert call_count == 3

        # 4th call should fail with circuit open WITHOUT calling the tool
        with pytest.raises(ToolCircuitOpenError, match="Circuit breaker open"):
            await executor.execute(ctx, config, always_fails, payload)

        # Verify tool was NOT called on 4th attempt (breaker prevented it)
        assert call_count == 3

        # 5th call should also be blocked
        with pytest.raises(ToolCircuitOpenError):
            await executor.execute(ctx, config, always_fails, payload)

        # Still only 3 calls
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_shared_breaker_half_open_and_recovery(self) -> None:
        """Test circuit breaker transitions through HALF_OPEN and recovers.

        This verifies that:
        1. Breaker transitions to HALF_OPEN after timeout
        2. Successful probe in HALF_OPEN closes the breaker
        3. Subsequent calls succeed normally
        """
        # Clear registry to ensure clean state
        registry = get_breaker_registry()
        registry.clear()

        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0
        should_fail = True

        async def controllable_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if should_fail:
                raise Exception("controlled failure")
            return {"result": "success"}

        ctx = ToolContext(trace_id="tr2", run_id="run2", tool_name="recovery_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=0,
            retry_jitter_max_ms=0,
            breaker_failure_threshold=3,
            breaker_window_seconds=60,
            breaker_half_open_seconds=2,  # Short timeout for testing
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        # Force breaker OPEN by causing 3 failures
        from backend.app.tools.executor import ToolExecutionError
        for _ in range(3):
            with pytest.raises(ToolExecutionError):
                await executor.execute(ctx, config, controllable_tool, payload)

        assert call_count == 3

        # Verify breaker is OPEN
        breaker = registry.get_or_create(
            tool_name="recovery_test",
            failure_threshold=3,
            window_seconds=60,
            half_open_seconds=2,
        )
        assert breaker.state == BreakerState.OPEN

        # Wait for half_open_seconds to transition to HALF_OPEN
        await asyncio.sleep(2.1)

        # Switch tool to succeed mode
        should_fail = False

        # Next call should be allowed (HALF_OPEN) and succeed
        result = await executor.execute(ctx, config, controllable_tool, payload)
        assert result.value == {"result": "success"}
        assert call_count == 4

        # Verify breaker is now CLOSED
        assert breaker.state == BreakerState.CLOSED

        # Subsequent calls should succeed normally
        result2 = await executor.execute(ctx, config, controllable_tool, payload)
        assert result2.value == {"result": "success"}
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_provenance_populated_on_fresh_call(self) -> None:
        """Test that Provenance metadata is populated on fresh tool execution."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        async def dummy_tool(payload: DummyPayload) -> dict[str, Any]:
            return {"data": "fresh"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="prov_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=0,
        )
        payload = DummyPayload(value="test")

        result = await executor.execute(ctx, config, dummy_tool, payload)

        # Verify result value
        assert result.value == {"data": "fresh"}

        # Verify provenance is populated
        assert result.provenance is not None
        assert result.provenance.source == "tool"
        assert result.provenance.cache_hit is False
        assert result.provenance.fetched_at is not None
        assert isinstance(result.provenance.fetched_at, datetime)

    @pytest.mark.asyncio
    async def test_provenance_cache_hit_flag_on_cached_call(self) -> None:
        """Test that Provenance.cache_hit is True for cached results."""
        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0

        async def dummy_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"data": "cached"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cache_prov_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            cache_ttl_seconds=3600,
        )
        payload = DummyPayload(value="test")

        # Use shared cache
        cache = ToolCache()

        # First call - should execute tool
        result1 = await executor.execute(ctx, config, dummy_tool, payload, cache=cache)
        assert result1.value == {"data": "cached"}
        assert result1.provenance.cache_hit is False
        assert call_count == 1
        original_fetched_at = result1.provenance.fetched_at

        # Second call - should hit cache
        result2 = await executor.execute(ctx, config, dummy_tool, payload, cache=cache)
        assert result2.value == {"data": "cached"}
        assert result2.provenance.cache_hit is True
        assert result2.provenance.fetched_at == original_fetched_at  # Same fetch time
        assert call_count == 1  # Tool not called again

    @pytest.mark.asyncio
    async def test_execute_end_to_end_retry_cache_provenance_and_metrics(self) -> None:
        """End-to-end integration test exercising all executor features together.

        This test verifies the complete execution path including:
        - Retry logic with jitter
        - Cache integration
        - Circuit breaker behavior
        - Provenance metadata
        - Metrics recording
        """
        # Register metrics
        from backend.app.utils.metrics import (
            tool_cache_hits_total,
            tool_errors_total,
            tool_latency_ms,
        )

        try:
            REGISTRY.register(tool_latency_ms)
        except Exception:
            pass
        try:
            REGISTRY.register(tool_errors_total)
        except Exception:
            pass
        try:
            REGISTRY.register(tool_cache_hits_total)
        except Exception:
            pass

        # Clear breaker registry
        registry = get_breaker_registry()
        registry.clear()

        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0
        fail_first_attempt = True

        async def flaky_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count, fail_first_attempt
            call_count += 1
            if fail_first_attempt and call_count == 1:
                raise Exception("first attempt fails")
            return {"data": f"call_{call_count}", "value": payload.value}

        ctx = ToolContext(trace_id="tr_e2e", run_id="run_e2e", tool_name="e2e_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=1,  # Allow 1 retry
            retry_jitter_min_ms=50,
            retry_jitter_max_ms=100,
            breaker_failure_threshold=3,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=3600,
        )
        payload = DummyPayload(value="integration_test")

        # Use shared cache
        cache = ToolCache()

        # === Phase 1: Retry behavior ===
        # First call - should retry after initial failure
        result1 = await executor.execute(ctx, config, flaky_tool, payload, cache=cache)
        assert result1.value == {"data": "call_2", "value": "integration_test"}
        assert result1.provenance.cache_hit is False
        assert call_count == 2  # Initial + 1 retry

        # === Phase 2: Cache behavior ===
        # Second call - should hit cache
        result2 = await executor.execute(ctx, config, flaky_tool, payload, cache=cache)
        assert result2.value == {"data": "call_2", "value": "integration_test"}  # Same result
        assert result2.provenance.cache_hit is True
        assert result2.provenance.fetched_at == result1.provenance.fetched_at
        assert call_count == 2  # Tool not called again

        # === Phase 3: Verify metrics ===
        from prometheus_client import generate_latest

        metrics_output = generate_latest().decode("utf-8")
        assert "tool_latency_ms" in metrics_output
        assert 'tool="e2e_test"' in metrics_output
        assert 'outcome="success"' in metrics_output
        assert 'outcome="cache_hit"' in metrics_output

        # === Phase 4: Different payload (cache miss) ===
        payload2 = DummyPayload(value="different")
        fail_first_attempt = False  # Don't fail this time

        result3 = await executor.execute(ctx, config, flaky_tool, payload2, cache=cache)
        assert result3.value["value"] == "different"
        assert result3.provenance.cache_hit is False
        assert call_count == 3  # New call

        # === Phase 5: Circuit breaker behavior ===
        # Force breaker to open by causing failures
        fail_first_attempt = True

        async def always_fails(payload: DummyPayload) -> dict[str, Any]:
            raise Exception("always fails")

        ctx_breaker = ToolContext(trace_id="tr_e2e", run_id="run_e2e", tool_name="breaker_tool")
        config_no_retry = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=50,
            retry_jitter_max_ms=100,
            breaker_failure_threshold=2,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=0,
        )

        from backend.app.tools.executor import ToolExecutionError

        # Cause 2 failures to open breaker
        for _ in range(2):
            with pytest.raises(ToolExecutionError):
                await executor.execute(ctx_breaker, config_no_retry, always_fails, payload)

        # Next call should be rejected by breaker
        with pytest.raises(ToolCircuitOpenError):
            await executor.execute(ctx_breaker, config_no_retry, always_fails, payload)

    @pytest.mark.asyncio
    async def test_cache_behavior_when_breaker_open(self) -> None:
        """Test that cache bypasses circuit breaker (cache checked before breaker).

        Design decision: Cached results are served even when breaker is OPEN.
        This trades freshness for availability - allowing stale-but-valid cached
        data to be served during tool outages.
        """
        # Clear breaker registry
        registry = get_breaker_registry()
        registry.clear()

        metrics = PrometheusToolMetrics()
        executor = ToolExecutor(metrics=metrics)

        call_count = 0

        async def flaky_tool(payload: DummyPayload) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("failing")
            return {"data": "success"}

        ctx = ToolContext(trace_id="tr1", run_id="run1", tool_name="cache_breaker_test")
        config = ToolConfig(
            soft_timeout_ms=2000,
            hard_timeout_ms=4000,
            retry_count=0,
            retry_jitter_min_ms=200,
            retry_jitter_max_ms=500,
            breaker_failure_threshold=2,
            breaker_window_seconds=60,
            breaker_half_open_seconds=30,
            cache_ttl_seconds=3600,  # Long TTL
        )
        payload = DummyPayload(value="test")

        # Use shared cache
        cache = ToolCache()

        # First, get a successful result into cache
        call_count = 2  # Set so next call (3) succeeds
        result1 = await executor.execute(ctx, config, flaky_tool, payload, cache=cache)
        assert result1.value == {"data": "success"}
        assert call_count == 3

        # Now cause breaker to open by making 2 failures with different payloads
        call_count = 0  # Reset to make it fail
        from backend.app.tools.executor import ToolExecutionError

        for i in range(2):
            payload_diff = DummyPayload(value=f"fail_{i}")  # Different payload to avoid cache
            with pytest.raises(ToolExecutionError):
                await executor.execute(ctx, config, flaky_tool, payload_diff, cache=cache)

        # Verify breaker is OPEN
        breaker = registry.get_or_create(
            tool_name="cache_breaker_test",
            failure_threshold=2,
            window_seconds=60,
            half_open_seconds=30,
        )
        assert breaker.state == BreakerState.OPEN

        # Now try original payload again - should hit cache and bypass breaker
        result2 = await executor.execute(ctx, config, flaky_tool, payload, cache=cache)
        assert result2.value == {"data": "success"}
        assert result2.provenance.cache_hit is True
        # call_count should still be 5 (1 success + 2 failures), no new call despite breaker being OPEN
        assert call_count == 2  # Only 2 failing calls after the successful one
