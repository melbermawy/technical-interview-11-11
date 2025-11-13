"""Test eval runner execution."""

import subprocess


def test_eval_runner_executes() -> None:
    """Test that eval runner runs without errors."""
    result = subprocess.run(
        ["python", "eval/runner.py"], capture_output=True, text=True
    )
    assert "Scenario: happy_stub" in result.stdout
    assert "Scenario: budget_violation_stub" in result.stdout


def test_happy_scenario_passes_all_predicates() -> None:
    """Test that happy_stub passes all predicates."""
    result = subprocess.run(
        ["python", "eval/runner.py"], capture_output=True, text=True
    )

    # happy_stub should pass all predicates
    assert "Scenario: happy_stub" in result.stdout
    assert "✓" in result.stdout or "PASS" in result.stdout

    # Check for success indicators in output
    lines = result.stdout.split("\n")
    happy_section = False
    for line in lines:
        if "happy_stub" in line:
            happy_section = True
        if happy_section and ("✓" in line or "PASS" in line):
            break
    else:
        # If we didn't find explicit pass markers, check that no FAIL appears
        # in the happy_stub section before the next scenario
        happy_lines = []
        in_happy = False
        for line in lines:
            if "happy_stub" in line:
                in_happy = True
            elif "budget_violation_stub" in line:
                break
            elif in_happy:
                happy_lines.append(line)
        assert not any("FAIL" in line for line in happy_lines)


def test_budget_violation_fails_predicate() -> None:
    """Test that budget_violation_stub fails at least one predicate."""
    result = subprocess.run(
        ["python", "eval/runner.py"], capture_output=True, text=True
    )

    # budget_violation_stub should fail at least one predicate
    assert "Scenario: budget_violation_stub" in result.stdout

    # Look for failure indicators
    lines = result.stdout.split("\n")
    budget_section = False
    found_failure = False
    for line in lines:
        if "budget_violation_stub" in line:
            budget_section = True
        if budget_section and ("✗" in line or "FAIL" in line):
            found_failure = True
            break
        if budget_section and "Scenario:" in line and "budget_violation" not in line:
            # Moved to next scenario
            break

    assert found_failure, "Expected budget_violation_stub to fail at least one predicate"


def test_runner_returns_nonzero_exit_code_on_failure() -> None:
    """Test that runner returns exit code 1 when predicates fail."""
    result = subprocess.run(
        ["python", "eval/runner.py"], capture_output=True, text=True
    )

    # Should return 1 because budget_violation_stub fails
    assert (
        result.returncode == 1
    ), f"Expected exit code 1, got {result.returncode}"


def test_runner_reports_summary() -> None:
    """Test that eval runner reports summary with pass/fail counts."""
    result = subprocess.run(
        ["python", "eval/runner.py"], capture_output=True, text=True
    )

    # Check summary
    assert "Summary" in result.stdout or "===" in result.stdout

    # Should show some passed and some failed
    lines = result.stdout.lower()
    assert "pass" in lines or "✓" in result.stdout
    assert "fail" in lines or "✗" in result.stdout
