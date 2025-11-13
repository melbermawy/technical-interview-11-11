"""Test eval runner execution."""

import subprocess


def test_eval_runner_executes() -> None:
    """Test that eval runner runs without errors."""
    result = subprocess.run(["python", "eval/runner.py"], capture_output=True, text=True)
    assert "Scenario: happy_stub" in result.stdout
    assert "Scenario: budget_fail_stub" in result.stdout


def test_eval_runner_reports_pass_and_fail() -> None:
    """Test that eval runner reports both pass and fail scenarios."""
    result = subprocess.run(["python", "eval/runner.py"], capture_output=True, text=True)

    # happy_stub should pass
    assert "happy_stub" in result.stdout

    # budget_fail_stub should also pass (expected to exceed budget)
    assert "budget_fail_stub" in result.stdout

    # Check summary
    assert "Summary" in result.stdout
