"""Test that constants are accessible from Settings and not duplicated."""

from backend.app.config import get_settings


def test_settings_accessible() -> None:
    """Test that Settings can be imported and accessed."""
    settings = get_settings()
    assert settings is not None


def test_buffer_constants_accessible() -> None:
    """Test that buffer constants are accessible."""
    settings = get_settings()
    assert settings.airport_buffer_min > 0
    assert settings.transit_buffer_min > 0


def test_timeout_constants_accessible() -> None:
    """Test that timeout constants are accessible."""
    settings = get_settings()
    assert settings.tool_soft_timeout_ms > 0
    assert settings.tool_hard_timeout_ms > settings.tool_soft_timeout_ms


def test_retry_jitter_constants_accessible() -> None:
    """Test that retry jitter constants are accessible."""
    settings = get_settings()
    assert settings.retry_jitter_min_ms > 0
    assert settings.retry_jitter_max_ms > settings.retry_jitter_min_ms


def test_circuit_breaker_constants_accessible() -> None:
    """Test that circuit breaker constants are accessible."""
    settings = get_settings()
    assert settings.circuit_breaker_failures > 0
    assert settings.circuit_breaker_window_sec > 0


def test_ttl_constants_accessible() -> None:
    """Test that TTL constants are accessible."""
    settings = get_settings()
    assert settings.fx_ttl_hours > 0
    assert settings.weather_ttl_hours > 0


def test_perf_budget_constants_accessible() -> None:
    """Test that performance budget constants are accessible."""
    settings = get_settings()
    assert settings.ttfe_budget_ms > 0
    assert settings.e2e_p50_budget_ms > 0
    assert settings.e2e_p95_budget_ms > settings.e2e_p50_budget_ms


def test_fanout_cap_accessible() -> None:
    """Test that fanout cap is accessible."""
    settings = get_settings()
    assert settings.fanout_cap > 0
    assert settings.fanout_cap == 4
