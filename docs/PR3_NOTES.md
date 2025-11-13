# PR-3: Tool Execution Nervous System

## Overview

PR-3 implements a production-ready, generic async tool executor with comprehensive resilience patterns: timeouts, retries with jitter, circuit breakers, caching, and cancellation support. It also exposes health checks and Prometheus metrics for observability.

## Architecture

### Core Components

1. **ToolExecutor** (`backend/app/tools/executor.py`)
   - Generic async executor for any tool function
   - Handles timeouts, retries, circuit breaking, caching, and cancellation
   - Emits Prometheus metrics and structured logs
   - Fully configurable via `Settings`

2. **Health Endpoint** (`/healthz`)
   - Checks database connectivity (SQLAlchemy SELECT 1)
   - Checks Redis connectivity (PING)
   - Optional outbound tool reachability check (disabled by default)
   - Returns 200 when core (DB + Redis) is healthy, 503 otherwise

3. **Metrics Endpoint** (`/metrics`)
   - Exposes Prometheus metrics in text format
   - Includes tool execution latencies, errors, and cache hits

## Executor API

### Basic Usage

```python
from backend.app.tools.executor import ToolExecutor, ToolContext, ToolConfig
from backend.app.utils.metrics import PrometheusToolMetrics
from pydantic import BaseModel

# Define your tool payload
class WeatherPayload(BaseModel):
    city: str
    date: str

# Define your tool function
async def get_weather(payload: WeatherPayload) -> dict:
    # ... fetch weather data ...
    return {"temp": 72, "conditions": "sunny"}

# Create executor
metrics = PrometheusToolMetrics()
executor = ToolExecutor(metrics=metrics)

# Execute tool
ctx = ToolContext(
    trace_id="trace-123",
    run_id="run-456",
    tool_name="weather"
)

config = ToolConfig(
    soft_timeout_ms=2000,
    hard_timeout_ms=4000,
    retry_count=1,
    retry_jitter_min_ms=200,
    retry_jitter_max_ms=500,
    breaker_failure_threshold=5,
    breaker_window_seconds=60,
    breaker_half_open_seconds=30,
    cache_ttl_seconds=3600  # 1 hour
)

payload = WeatherPayload(city="San Francisco", date="2025-01-15")
result = await executor.execute(ctx, config, get_weather, payload)

# Access result value and provenance (PR-3b)
weather_data = result.value  # {"temp": 72, "conditions": "sunny"}
provenance = result.provenance  # Provenance metadata
print(f"Fetched at: {provenance.fetched_at}")
print(f"Cache hit: {provenance.cache_hit}")
```

### Error Types

The executor raises typed exceptions for different failure modes:

- **`ToolTimeoutError`**: Raised when tool exceeds hard timeout after all retry attempts
- **`ToolCircuitOpenError`**: Raised when circuit breaker is in OPEN state
- **`ToolCancelledError`**: Raised when execution is cancelled via CancelToken
- **`ToolExecutionError`**: Raised for other tool execution failures after retries

### Cancellation

Cancellation is explicit via `CancelToken`:

```python
from backend.app.tools.executor import CancelToken

cancel_token = CancelToken(cancelled=False)

# Execute with cancellation support
result = await executor.execute(ctx, config, get_weather, payload, cancel_token)

# Cancel from another coroutine
cancel_token.cancelled = True
```

**Cancellation semantics**:
- Checked before execution starts
- Checked between retry attempts
- Does NOT forcibly abort running tool (tool must check token internally if needed)
- Cancellations do NOT count towards circuit breaker failures

## Circuit Breaker Semantics

The circuit breaker implements the classic pattern with three states:

### States

1. **CLOSED** (default)
   - Normal operation
   - Tool executions proceed normally
   - Failures are tracked in a sliding time window

2. **OPEN**
   - Triggered after `breaker_failure_threshold` failures within `breaker_window_seconds`
   - All executions immediately fail with `ToolCircuitOpenError`
   - No tool calls are attempted
   - State automatically transitions to HALF_OPEN after `breaker_half_open_seconds`

3. **HALF_OPEN**
   - Allows a single test execution to proceed
   - On success: transitions back to CLOSED and clears failure history
   - On failure: transitions back to OPEN and resets the timer

### What Counts as a Failure?

- Timeouts (exceeding hard timeout)
- Tool exceptions (non-timeout errors)
- **Cancellations do NOT count as failures**

### Per-Tool Isolation & Shared State (PR-3b)

Each tool has its own independent circuit breaker. A failure in `weather` does not affect the breaker state for `flights` or `fx_rates`.

**Important**: Circuit breaker state is **shared across all executor invocations** for the same tool via a global `BreakerRegistry`. This ensures that failures from one request propagate to subsequent requests, providing true per-tool isolation as required by SPEC §4.2.

Example:
```python
# First request fails 5 times → breaker opens
await executor1.execute(ctx1, config, failing_tool, payload)  # Fails 5x

# Second request (different executor instance) sees OPEN breaker
await executor2.execute(ctx2, config, failing_tool, payload)  # ToolCircuitOpenError
```

## Cache Semantics

### Cache Key Generation

Cache keys are deterministic and content-based:

```
key = "{tool_name}:{sha256(sorted_json(payload))}"
```

This ensures:
- Same payload → same cache key → cache hit
- Different payload order → same cache key (sorted JSON)
- Different payload values → different cache key

### Cache TTL

Each tool can specify its own `cache_ttl_seconds`:

- `cache_ttl_seconds = 0`: Caching disabled
- `cache_ttl_seconds > 0`: Results cached for specified duration

Example configuration:
```python
# In Settings
weather_ttl_seconds: int = 24 * 3600  # 24 hours
fx_ttl_seconds: int = 24 * 3600       # 24 hours
```

### Cache Behavior

1. On cache hit:
   - Tool function is NOT executed
   - Cached result is returned immediately
   - `cache_hit=True` is logged and recorded in metrics

2. On cache miss or expired entry:
   - Tool function is executed normally
   - Result is cached with TTL
   - `cache_hit=False` is logged

3. Cache storage:
   - In-memory (not persistent across restarts)
   - Can be extended to Redis in future PRs

### Cache vs Circuit Breaker Priority (PR-3b)

**Design Decision**: Cache check happens **BEFORE** circuit breaker check.

This means:
- Cached results are served even when the circuit breaker is OPEN
- Trades freshness for availability during outages
- Allows serving stale-but-valid data when tool is failing

Example:
```python
# 1. Successful call caches result
result1 = await executor.execute(ctx, config, tool, payload)  # Success, cached

# 2. Different payload fails 5 times, opens breaker
await executor.execute(ctx, config, tool, other_payload)  # Fails 5x → breaker OPEN

# 3. Original payload still returns cached result, bypassing breaker
result2 = await executor.execute(ctx, config, tool, payload)  # Cache hit, breaker bypassed
```

**Alternative design** (rejected): Check breaker first would make breaker more strict but reduce cache utility during outages.

## Provenance Metadata (PR-3b)

### Overview

Per SPEC §3.4, all tool execution results include `Provenance` metadata for citation tracking. The executor returns a `ToolResult[T]` wrapper containing both the result value and provenance information.

### Provenance Structure

```python
from backend.app.models.common import Provenance

@dataclass
class Provenance(BaseModel):
    source: Literal["tool", "rag", "user"]
    ref_id: str | None
    source_url: str | None
    fetched_at: datetime
    cache_hit: bool | None
    response_digest: str | None
```

### Usage

```python
result = await executor.execute(ctx, config, get_weather, payload)

# Access result value
weather_data = result.value  # {"temp": 72, "conditions": "sunny"}

# Access provenance
prov = result.provenance
print(f"Source: {prov.source}")           # "tool"
print(f"Fetched at: {prov.fetched_at}")   # datetime(2025, 1, 15, ...)
print(f"Cache hit: {prov.cache_hit}")      # False or True
```

### Cache Hit Detection

The `cache_hit` field distinguishes fresh vs cached data:

- **Fresh execution**: `cache_hit=False`, `fetched_at` = current execution time
- **Cache hit**: `cache_hit=True`, `fetched_at` = original fetch time (preserved from cache)

This enables downstream components (synthesizer, verifier) to:
1. Measure citation coverage accurately
2. Cite data sources with original fetch times
3. Distinguish stale cached data from fresh results

### Return Type

**PR-3b Change**: `execute()` now returns `ToolResult[T]` instead of `T`:

```python
# Before PR-3b
result: dict = await executor.execute(...)  # dict

# After PR-3b
result: ToolResult[dict] = await executor.execute(...)
data = result.value  # dict
prov = result.provenance  # Provenance
```

**Migration**: Existing code must be updated to access `.value` instead of using result directly.

## Retry Logic

### Retry Configuration

- `retry_count`: Number of retry attempts (default: 1)
- `retry_jitter_min_ms`: Minimum jitter delay in milliseconds (default: 200)
- `retry_jitter_max_ms`: Maximum jitter delay in milliseconds (default: 500)

### Retry Behavior

1. **Initial attempt** executes immediately
2. On failure (timeout or exception):
   - If retries remain, wait for random jitter between `[retry_jitter_min_ms, retry_jitter_max_ms]`
   - Check cancellation token
   - Execute next attempt
3. Repeat until success or all attempts exhausted

### Why Jitter?

Jitter prevents thundering herd problems when multiple runs fail simultaneously and retry at the same time. Random delays spread out retry attempts.

## Timeout Semantics

### Soft vs Hard Timeout

- **Soft timeout** (`soft_timeout_ms`): Not currently enforced (reserved for future use)
- **Hard timeout** (`hard_timeout_ms`): Enforced per attempt using `asyncio.wait_for()`

### Timeout Behavior

1. Each retry attempt gets the full hard timeout
2. Timeout is NOT cumulative across retries
3. If tool exceeds hard timeout:
   - Attempt is cancelled
   - Counted as a failure for circuit breaker
   - Retry logic kicks in (if retries remain)

## Metrics

### Exported Metrics

1. **`tool_latency_ms`** (Histogram)
   - Labels: `tool`, `outcome`
   - Buckets: `[10, 50, 100, 200, 500, 1000, 2000, 4000, 8000]` milliseconds
   - Tracks tool execution latency
   - Outcome values: `"success"`, `"timeout"`, `"error"`, `"circuit_open"`, `"cancelled"`

2. **`tool_errors_total`** (Counter)
   - Labels: `tool`, `reason`
   - Incremented on tool failures
   - Reason values: `"timeout"`, `"circuit_open"`, `"exception"`, `"cancelled"`

3. **`tool_cache_hits_total`** (Counter)
   - Labels: `tool`
   - Incremented when cache hit occurs

### Scraping Metrics

```bash
curl http://localhost:8000/metrics
```

Example output:
```
# HELP tool_latency_ms Tool execution latency in milliseconds
# TYPE tool_latency_ms histogram
tool_latency_ms_bucket{tool="weather",outcome="success",le="10"} 0.0
tool_latency_ms_bucket{tool="weather",outcome="success",le="50"} 0.0
tool_latency_ms_bucket{tool="weather",outcome="success",le="100"} 1.0
tool_latency_ms_count{tool="weather",outcome="success"} 1.0
tool_latency_ms_sum{tool="weather",outcome="success"} 87.5

# HELP tool_cache_hits_total Total tool cache hits
# TYPE tool_cache_hits_total counter
tool_cache_hits_total{tool="weather"} 3.0
```

## Health Checks

### Endpoint: `GET /healthz`

Returns JSON with component health status.

### Response Structure

**Success (200 OK)**:
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "tools": "ok"  // if outbound check enabled
}
```

**Failure (503 Service Unavailable)**:
```json
{
  "status": "degraded",
  "db": "connection refused",
  "redis": "ok",
  "tools": "skipped"
}
```

### Health Check Logic

1. **DB Check**: Execute `SELECT 1` via SQLAlchemy
2. **Redis Check**: Execute `PING` command
3. **Tools Check** (optional, disabled by default):
   - Executes a test tool with short timeout (500ms)
   - Configured via `enable_outbound_healthcheck` setting

### Status Codes

- **200**: Core components (DB + Redis) are healthy
- **503**: One or more core components are unhealthy

Note: Tool check failures do NOT affect status code (only core matters).

## Configuration

All executor behavior is controlled via `Settings` (`backend/app/config.py`):

### Timeout Settings
```python
tool_soft_timeout_ms: int = 2000      # Soft timeout (future use)
tool_hard_timeout_ms: int = 4000      # Hard timeout per attempt
```

### Retry Settings
```python
tool_retry_count: int = 1             # Number of retries
retry_jitter_min_ms: int = 200        # Min jitter delay
retry_jitter_max_ms: int = 500        # Max jitter delay
```

### Circuit Breaker Settings
```python
tool_breaker_failure_threshold: int = 5      # Failures to open breaker
tool_breaker_window_seconds: int = 60        # Time window for counting
tool_breaker_half_open_seconds: int = 30     # Wait before HALF_OPEN
```

### Cache Settings
```python
weather_ttl_seconds: int = 24 * 3600   # Weather cache TTL
fx_ttl_seconds: int = 24 * 3600        # FX rates cache TTL
```

### Health Check Settings
```python
enable_outbound_healthcheck: bool = False    # Enable tool check
health_tool_timeout_ms: int = 500            # Tool check timeout
```

## Structured Logging

All tool executions emit structured JSON logs via `StructuredToolLogger`:

```json
{
  "trace_id": "trace-123",
  "run_id": "run-456",
  "tool": "weather",
  "attempt": 1,
  "outcome": "success",
  "latency_ms": 87.5,
  "cache_hit": false
}
```

On errors:
```json
{
  "trace_id": "trace-123",
  "run_id": "run-456",
  "tool": "weather",
  "attempt": 2,
  "outcome": "timeout",
  "latency_ms": 4001.2,
  "cache_hit": false,
  "error_reason": "exceeded hard timeout"
}
```

## Testing

Comprehensive test coverage in:
- `tests/unit/test_tool_executor.py`: Unit tests for executor logic
- `tests/integration/test_health_metrics.py`: Integration tests for endpoints

### Test Coverage

1. **Timeout behavior**: Tool exceeds hard timeout → `ToolTimeoutError`
2. **Retry + jitter**: Flaky tool retries with random delay
3. **Circuit breaker**:
   - 5 failures → OPEN state
   - HALF_OPEN recovery after wait period
   - Cancellations don't count towards failures
4. **Cache integration**: First call executes, second hits cache
5. **Cancellation**: Before execute and between attempts
6. **Metrics wiring**: Prometheus metrics are recorded
7. **Health endpoint**: Returns 200 when healthy, 503 when degraded
8. **Metrics endpoint**: Exposes Prometheus text format

### Running Tests

```bash
# Run all tests
pytest

# Run only executor tests
pytest tests/unit/test_tool_executor.py -v

# Run only integration tests
pytest tests/integration/test_health_metrics.py -v
```

## Design Decisions

### Why In-Memory Cache?

- Simplicity for PR-3 scope
- Sufficient for short-lived tool results
- Can be extended to Redis in future PRs without API changes

### Why Per-Attempt Timeout?

- Gives each retry a fair chance
- Prevents early exhaustion of time budget on first attempt
- More predictable behavior for flaky services

### Why CancelToken Pattern?

- Explicit cancellation signaling
- No forceful task cancellation (avoids resource leaks)
- Cancellations clearly distinguished from timeouts/errors
- Doesn't pollute circuit breaker failure counts

### Why Separate ToolMetrics/ToolLogger Interfaces?

- Testability: Can inject mocks for unit tests
- Extensibility: Can swap Prometheus for other backends
- Separation of concerns: Executor doesn't depend on specific metric system

## Future Enhancements

While not in scope for PR-3, the design supports:

1. **Redis-backed cache**: Replace in-memory cache with Redis for persistence
2. **Soft timeout enforcement**: Add cancellation request at soft timeout
3. **Adaptive timeouts**: Adjust timeout based on p95 latencies
4. **Distributed circuit breaker**: Share breaker state across replicas via Redis
5. **Streaming results**: Support SSE for long-running tools
6. **Tool-specific breaker tuning**: Different thresholds per tool type

## API Stability

The following APIs are considered stable for PR-3:

- `ToolExecutor.execute()` signature
- `ToolContext`, `ToolConfig` dataclasses
- `CancelToken` interface
- Exception types (ToolTimeoutError, etc.)
- Metrics names and labels
- `/healthz` and `/metrics` endpoint contracts

Changes to these APIs should be avoided or carefully versioned.

## Migration Notes

For integrating PR-3 into existing code:

1. **Wrap existing tool functions**: No changes needed, just pass to executor
2. **Configure timeouts**: Set appropriate values in `.env` or `Settings`
3. **Monitor metrics**: Set up Prometheus scraping of `/metrics`
4. **Set up health checks**: Point load balancer/k8s probes to `/healthz`
5. **Add trace_id/run_id**: Ensure these are available in your request context

## PR-3b Enhancements

PR-3b addressed critical gaps identified in the initial PR-3 audit:

### 1. Shared Circuit Breaker State ✅

**Problem**: Circuit breakers were created per `execute()` call, so state wasn't shared.
**Solution**: Added global `BreakerRegistry` that maintains per-tool breaker state across all executor invocations.
**Impact**: Circuit breaker now works as specified - failures propagate across requests.

### 2. Provenance Integration ✅

**Problem**: No provenance metadata on tool results, breaking citation tracking requirements.
**Solution**: Executor now returns `ToolResult[T]` wrapper with `Provenance` metadata including `cache_hit`, `fetched_at`, `source`.
**Impact**: Downstream synthesizer/verifier can track data sources and measure citation coverage per SPEC §3.4.

### 3. Integration Tests ✅

**Problem**: No end-to-end test exercising all features together.
**Solution**: Added `test_execute_end_to_end_retry_cache_provenance_and_metrics` covering retry, cache, breaker, provenance, and metrics in one flow.
**Impact**: Confidence in combined behavior before PR-4+ integration.

### 4. Health Endpoint JSON Bug ✅

**Problem**: `/healthz` returned `str(dict)` on 503 errors instead of valid JSON.
**Solution**: Fixed to return `json.dumps(response_body)`.
**Impact**: Clients can parse 503 responses correctly.

### 5. Enhanced Metrics Tests ✅

**Problem**: Metrics tests only checked presence, not actual labels/values.
**Solution**: Enhanced test to verify specific outcome labels (`success`, `cache_hit`, `timeout`) and error reasons.
**Impact**: Higher confidence in observability correctness.

### 6. Documented Semantics ✅

**Problem**: Cache-vs-breaker priority and soft timeout status were undocumented/ambiguous.
**Solution**:
- Added code comments explaining cache-before-breaker design decision
- Added test `test_cache_behavior_when_breaker_open` verifying this
- Updated module docstring to clarify soft timeout is "reserved for future use"

**Impact**: Clear semantics for future maintainers and PR-4+ integration.

## Summary

PR-3 delivers a production-ready tool execution layer with:

- ✅ Resilience: Timeouts, retries, circuit breakers (with shared per-tool state)
- ✅ Performance: Per-tool caching with TTLs
- ✅ Observability: Prometheus metrics + structured logging
- ✅ Operability: Health checks for k8s/monitoring
- ✅ Safety: Explicit cancellation, no tool-specific hacks
- ✅ Testability: Injectable sleep, comprehensive test coverage (27 unit tests)
- ✅ Configurability: All knobs in Settings, no magic literals
- ✅ Traceability: Provenance metadata on all results (PR-3b)

**PR-3b Status**: All [HIGH] priority issues from audit addressed. Ready for PR-4 (LangGraph integration).

The executor is generic and ready to support any tool (weather, flights, FX rates, etc.) without modification.
