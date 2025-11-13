"""Generic async tool executor with timeouts, retries, circuit breaker, and caching.

Per SPEC §§4-6: Implements tool execution with:
- Hard timeout (4s per attempt; soft timeout reserved for future use)
- Bounded retries (1 retry with 200-500ms jitter)
- Per-tool circuit breaker (5 failures/60s, shared state via registry)
- Cache with TTLs
- Cancellation support
- Metrics and structured logging
"""

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from backend.app.models.common import Provenance

T = TypeVar("T")


# Exception types
class ToolTimeoutError(Exception):
    """Tool execution exceeded timeout."""

    pass


class ToolCircuitOpenError(Exception):
    """Circuit breaker is open for this tool."""

    pass


class ToolExecutionError(Exception):
    """Tool execution failed."""

    pass


class ToolCancelledError(Exception):
    """Tool execution was cancelled."""

    pass


@dataclass
class ToolResult(Generic[T]):
    """Wrapper for tool results with provenance metadata.

    This allows attaching Provenance metadata to tool execution results
    per SPEC §3.4 requirement for citation tracking.
    """

    value: T
    provenance: Provenance


# Context and config types
@dataclass(frozen=True)
class ToolContext:
    """Context for tool execution with tracing."""

    trace_id: str
    run_id: str | None
    tool_name: str


@dataclass
class CancelToken:
    """Token for cancellation signaling."""

    cancelled: bool = False

    def throw_if_cancelled(self) -> None:
        """Raise ToolCancelledError if cancelled."""
        if self.cancelled:
            raise ToolCancelledError("run cancelled")


@dataclass
class ToolConfig:
    """Configuration for tool execution."""

    soft_timeout_ms: int
    hard_timeout_ms: int
    retry_count: int
    retry_jitter_min_ms: int
    retry_jitter_max_ms: int
    breaker_failure_threshold: int = 5
    breaker_window_seconds: int = 60
    breaker_half_open_seconds: int = 30
    cache_ttl_seconds: int = 0


class BreakerState(str, Enum):
    """Circuit breaker state."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Per-tool circuit breaker.

    Tracks failures within a time window and opens after threshold.
    """

    tool_name: str
    failure_threshold: int
    window_seconds: int
    half_open_seconds: int
    state: BreakerState = BreakerState.CLOSED
    failure_times: list[datetime] = field(default_factory=list)
    opened_at: datetime | None = None

    def record_success(self) -> None:
        """Record successful execution."""
        if self.state == BreakerState.HALF_OPEN:
            # Success in half-open -> reset to closed
            self.state = BreakerState.CLOSED
            self.failure_times.clear()
            self.opened_at = None

    def record_failure(self, now: datetime) -> None:
        """Record failed execution (only for retryable errors)."""
        # Clean old failures outside window
        cutoff = now - timedelta(seconds=self.window_seconds)
        self.failure_times = [t for t in self.failure_times if t > cutoff]

        # Add new failure
        self.failure_times.append(now)

        # Check if we should open
        if len(self.failure_times) >= self.failure_threshold:
            self.state = BreakerState.OPEN
            self.opened_at = now

    def check_and_update_state(self, now: datetime) -> BreakerState:
        """Check if breaker should transition states."""
        if self.state == BreakerState.OPEN:
            if self.opened_at and (now - self.opened_at).total_seconds() >= self.half_open_seconds:
                # Transition to half-open
                self.state = BreakerState.HALF_OPEN

        return self.state

    def is_open(self, now: datetime) -> bool:
        """Check if breaker is currently open (rejecting calls)."""
        state = self.check_and_update_state(now)
        return state == BreakerState.OPEN


class BreakerRegistry:
    """Registry of per-tool circuit breakers with shared state.

    This ensures circuit breaker state is maintained across multiple executor
    calls for the same tool, as required by SPEC §4.2.
    """

    def __init__(self) -> None:
        self._by_tool: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        tool_name: str,
        failure_threshold: int,
        window_seconds: int,
        half_open_seconds: int,
    ) -> CircuitBreaker:
        """Get existing breaker for tool or create new one with given config."""
        if tool_name not in self._by_tool:
            self._by_tool[tool_name] = CircuitBreaker(
                tool_name=tool_name,
                failure_threshold=failure_threshold,
                window_seconds=window_seconds,
                half_open_seconds=half_open_seconds,
            )
        return self._by_tool[tool_name]

    def clear(self) -> None:
        """Clear all breakers (useful for testing)."""
        self._by_tool.clear()


# Global registry instance for shared breaker state
_global_breaker_registry = BreakerRegistry()


def get_breaker_registry() -> BreakerRegistry:
    """Get the global breaker registry instance."""
    return _global_breaker_registry


@dataclass
class CacheEntry(Generic[T]):
    """Cached tool result with metadata."""

    value: T
    cached_at: datetime
    ttl_seconds: int

    def is_fresh(self, now: datetime) -> bool:
        """Check if cache entry is still valid."""
        return (now - self.cached_at).total_seconds() < self.ttl_seconds


class ToolCache:
    """In-memory cache for tool results."""

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry[Any]] = {}

    def make_key(self, tool_name: str, payload: BaseModel) -> str:
        """Generate deterministic cache key from payload."""
        data = payload.model_dump(mode="json")
        sorted_json = json.dumps(data, sort_keys=True)
        hash_digest = hashlib.sha256(sorted_json.encode()).hexdigest()
        return f"{tool_name}:{hash_digest}"

    def get(self, key: str, now: datetime) -> Any | None:
        """Get cached value if fresh, None otherwise."""
        entry = self._cache.get(key)
        if entry and entry.is_fresh(now):
            return entry.value
        elif entry:
            # Expired - remove
            del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl_seconds: int, now: datetime) -> None:
        """Store value in cache with TTL."""
        self._cache[key] = CacheEntry(value=value, cached_at=now, ttl_seconds=ttl_seconds)


# Metrics interface (to be implemented by actual metrics system)
class ToolMetrics:
    """Interface for tool execution metrics."""

    def record_latency(self, tool: str, outcome: str, latency_ms: float) -> None:
        """Record tool execution latency."""
        pass

    def inc_error(self, tool: str, reason: str) -> None:
        """Increment error counter."""
        pass

    def inc_cache_hit(self, tool: str) -> None:
        """Increment cache hit counter."""
        pass


# Logging interface
class ToolLogger:
    """Interface for structured logging."""

    def log_attempt(
        self,
        ctx: ToolContext,
        attempt: int,
        outcome: str,
        latency_ms: float,
        cache_hit: bool = False,
        error_reason: str | None = None,
    ) -> None:
        """Log tool execution attempt."""
        pass


# Main executor
class ToolExecutor:
    """Generic async tool executor with full error handling."""

    def __init__(
        self,
        metrics: ToolMetrics | None = None,
        logger: ToolLogger | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize executor.

        Args:
            metrics: Metrics recorder (optional, defaults to no-op)
            logger: Structured logger (optional, defaults to no-op)
            sleep_fn: Injectable sleep function (default: asyncio.sleep)
        """
        self._metrics = metrics or ToolMetrics()
        self._logger = logger or ToolLogger()
        self._sleep = sleep_fn or asyncio.sleep

    async def execute(
        self,
        ctx: ToolContext,
        config: ToolConfig,
        fn: Callable[[BaseModel], Awaitable[T]],
        payload: BaseModel,
        cancel_token: CancelToken | None = None,
        *,
        cache: ToolCache | None = None,
        breaker: CircuitBreaker | None = None,
        cache_ttl_seconds: int = 0,
    ) -> ToolResult[T]:
        """Execute tool with full error handling pipeline.

        Args:
            ctx: Tool context with trace_id/run_id
            config: Execution configuration
            fn: Async function to execute
            payload: Tool input payload
            cancel_token: Cancellation token (optional, defaults to not cancelled)
            cache: Cache store (optional, creates new if not provided)
            breaker: Circuit breaker (optional, uses shared registry by default)
            cache_ttl_seconds: Cache TTL (0 = no caching)

        Returns:
            ToolResult[T] wrapping the tool result with Provenance metadata

        Raises:
            ToolTimeoutError: Execution exceeded hard timeout
            ToolCircuitOpenError: Circuit breaker is open
            ToolCancelledError: Execution was cancelled
            ToolExecutionError: Other execution failures
        """
        start_time = time.monotonic()

        # Use defaults if not provided
        if cancel_token is None:
            cancel_token = CancelToken()
        if cache is None:
            cache = ToolCache()
        if breaker is None:
            # Use shared per-tool breaker from registry (SPEC §4.2)
            registry = get_breaker_registry()
            breaker = registry.get_or_create(
                tool_name=ctx.tool_name,
                failure_threshold=config.breaker_failure_threshold,
                window_seconds=config.breaker_window_seconds,
                half_open_seconds=config.breaker_half_open_seconds,
            )

        # Check cancellation before starting
        cancel_token.throw_if_cancelled()

        # Check cache first (BEFORE breaker check)
        # Design decision: Cached results bypass circuit breaker. This allows serving
        # stale-but-valid cached data even when tool is failing, trading freshness for
        # availability. Alternative would be to check breaker first, which would make
        # breaker more strict but reduce cache utility during outages.
        now = datetime.now()
        cache_ttl_seconds = cache_ttl_seconds or config.cache_ttl_seconds
        if cache_ttl_seconds > 0:
            cache_key = cache.make_key(ctx.tool_name, payload)
            cached_entry = cache.get(cache_key, now)
            if cached_entry is not None:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self._metrics.record_latency(ctx.tool_name, "cache_hit", elapsed_ms)
                self._metrics.inc_cache_hit(ctx.tool_name)
                self._logger.log_attempt(ctx, 0, "cache_hit", elapsed_ms, cache_hit=True)

                # Unpack cached entry to get result and original fetch time
                cached_result, cached_at = cached_entry

                # Create provenance for cache hit
                provenance = Provenance(
                    source="tool",
                    fetched_at=cached_at,
                    cache_hit=True,
                    response_digest=None,  # Could add digest later
                )
                return ToolResult(value=cached_result, provenance=provenance)

        # Check circuit breaker
        if breaker.is_open(now):
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._metrics.record_latency(ctx.tool_name, "breaker_open", elapsed_ms)
            self._metrics.inc_error(ctx.tool_name, "breaker_open")
            self._logger.log_attempt(
                ctx, 0, "breaker_open", elapsed_ms, error_reason="breaker_open"
            )
            raise ToolCircuitOpenError(f"Circuit breaker open for {ctx.tool_name}")

        # Execute with retries
        last_error: Exception | None = None
        for attempt in range(config.retry_count + 1):
            # Check cancellation before each attempt
            cancel_token.throw_if_cancelled()

            attempt_start = time.monotonic()

            try:
                # Execute with hard timeout
                hard_timeout_sec = config.hard_timeout_ms / 1000
                result = await asyncio.wait_for(fn(payload), timeout=hard_timeout_sec)

                # Success
                elapsed_ms = (time.monotonic() - attempt_start) * 1000
                fetched_at = datetime.now()
                breaker.record_success()
                self._metrics.record_latency(ctx.tool_name, "success", elapsed_ms)
                self._logger.log_attempt(ctx, attempt + 1, "success", elapsed_ms)

                # Cache result with fetch time if configured
                if cache_ttl_seconds > 0:
                    cache.set(cache_key, (result, fetched_at), cache_ttl_seconds, now)

                # Create provenance for fresh execution
                provenance = Provenance(
                    source="tool",
                    fetched_at=fetched_at,
                    cache_hit=False,
                    response_digest=None,  # Could add digest later
                )
                return ToolResult(value=result, provenance=provenance)

            except TimeoutError as e:
                elapsed_ms = (time.monotonic() - attempt_start) * 1000
                last_error = e

                # Timeout is retryable
                self._metrics.inc_error(ctx.tool_name, "timeout")
                self._logger.log_attempt(
                    ctx, attempt + 1, "timeout", elapsed_ms, error_reason="timeout"
                )

                # Record as breaker failure
                breaker.record_failure(datetime.now())

                # Retry if not last attempt
                if attempt < config.retry_count:
                    cancel_token.throw_if_cancelled()
                    jitter_ms = random.uniform(
                        config.retry_jitter_min_ms, config.retry_jitter_max_ms
                    )
                    await self._sleep(jitter_ms / 1000)
                    continue

            except ToolCancelledError:
                # Cancellation - don't count towards breaker
                elapsed_ms = (time.monotonic() - attempt_start) * 1000
                self._metrics.record_latency(ctx.tool_name, "cancelled", elapsed_ms)
                self._logger.log_attempt(
                    ctx, attempt + 1, "cancelled", elapsed_ms, error_reason="cancelled"
                )
                raise

            except Exception as e:
                # Other errors - treat as retryable for now
                elapsed_ms = (time.monotonic() - attempt_start) * 1000
                last_error = e

                self._metrics.inc_error(ctx.tool_name, "execution_error")
                self._logger.log_attempt(
                    ctx, attempt + 1, "error", elapsed_ms, error_reason=type(e).__name__
                )

                # Record as breaker failure
                breaker.record_failure(datetime.now())

                # Retry if not last attempt
                if attempt < config.retry_count:
                    cancel_token.throw_if_cancelled()
                    jitter_ms = random.uniform(
                        config.retry_jitter_min_ms, config.retry_jitter_max_ms
                    )
                    await self._sleep(jitter_ms / 1000)
                    continue

        # All attempts exhausted
        if isinstance(last_error, asyncio.TimeoutError):
            raise ToolTimeoutError(f"Tool {ctx.tool_name} timed out after all retries")
        else:
            raise ToolExecutionError(
                f"Tool {ctx.tool_name} failed after all retries"
            ) from last_error
