"""Prometheus metrics for tool execution - PR-3."""

from prometheus_client import Counter, Histogram

# Tool execution metrics
tool_latency_ms = Histogram(
    "tool_latency_ms",
    "Tool execution latency in milliseconds",
    ["tool", "outcome"],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 4000, 8000],
)

tool_errors_total = Counter(
    "tool_errors_total",
    "Total tool execution errors",
    ["tool", "reason"],
)

tool_cache_hits_total = Counter(
    "tool_cache_hits_total",
    "Total tool cache hits",
    ["tool"],
)


class PrometheusToolMetrics:
    """Prometheus-based tool metrics implementation."""

    def record_latency(self, tool: str, outcome: str, latency_ms: float) -> None:
        """Record tool execution latency."""
        tool_latency_ms.labels(tool=tool, outcome=outcome).observe(latency_ms)

    def inc_error(self, tool: str, reason: str) -> None:
        """Increment error counter."""
        tool_errors_total.labels(tool=tool, reason=reason).inc()

    def inc_cache_hit(self, tool: str) -> None:
        """Increment cache hit counter."""
        tool_cache_hits_total.labels(tool=tool).inc()
