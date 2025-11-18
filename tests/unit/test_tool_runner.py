"""Unit tests for tool runner (PR-11A)."""

import uuid
from datetime import UTC

import pytest

from backend.app.orchestration.state import GraphState
from backend.app.orchestration.tools import run_tool


@pytest.mark.asyncio
async def test_run_tool_success_logs_entry() -> None:
    """Test that successful tool call logs a ToolCallLog entry."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def fake_call():
        return {"result": "success"}

    result = await run_tool(
        name="test.tool",
        state=state,
        input_summary={"param": "value"},
        output_counter=lambda r: {"count": 1},
        call=fake_call,
    )

    # Verify result returned
    assert result == {"result": "success"}

    # Verify log entry
    assert len(state.tool_calls) == 1
    log = state.tool_calls[0]
    assert log.name == "test.tool"
    assert log.success is True
    assert log.error is None
    assert log.duration_ms >= 0
    assert log.input_summary == {"param": "value"}
    assert log.output_summary == {"count": 1}


@pytest.mark.asyncio
async def test_run_tool_failure_logs_and_raises() -> None:
    """Test that failed tool call logs error and re-raises exception."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def failing_call():
        raise ValueError("Tool failed")

    # Verify exception is re-raised
    with pytest.raises(ValueError, match="Tool failed"):
        await run_tool(
            name="test.tool",
            state=state,
            input_summary={"param": "value"},
            call=failing_call,
        )

    # Verify log entry recorded
    assert len(state.tool_calls) == 1
    log = state.tool_calls[0]
    assert log.name == "test.tool"
    assert log.success is False
    assert log.error == "Tool failed"
    assert log.duration_ms >= 0
    assert log.input_summary == {"param": "value"}
    assert log.output_summary == {}


@pytest.mark.asyncio
async def test_run_tool_uses_utc_timestamps() -> None:
    """Test that timestamps are in UTC timezone."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def fake_call():
        return "result"

    await run_tool(
        name="test.tool",
        state=state,
        call=fake_call,
    )

    log = state.tool_calls[0]
    assert log.started_at.tzinfo == UTC
    assert log.finished_at.tzinfo == UTC


@pytest.mark.asyncio
async def test_run_tool_deterministic_output_summary() -> None:
    """Test that output summary is deterministic given same input."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def fake_call():
        return [1, 2, 3]

    # Run twice
    await run_tool(
        name="test.tool",
        state=state,
        input_summary={"key": "value"},
        output_counter=lambda r: {"count": len(r)},
        call=fake_call,
    )

    await run_tool(
        name="test.tool",
        state=state,
        input_summary={"key": "value"},
        output_counter=lambda r: {"count": len(r)},
        call=fake_call,
    )

    # Verify both logs have same summaries (excluding timestamps/duration)
    assert len(state.tool_calls) == 2
    log1, log2 = state.tool_calls

    assert log1.name == log2.name
    assert log1.success == log2.success
    assert log1.input_summary == log2.input_summary
    assert log1.output_summary == log2.output_summary


@pytest.mark.asyncio
async def test_run_tool_default_empty_summaries() -> None:
    """Test that summaries default to empty dict when not provided."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def fake_call():
        return "result"

    await run_tool(
        name="test.tool",
        state=state,
        call=fake_call,
        # No input_summary or output_counter provided
    )

    log = state.tool_calls[0]
    assert log.input_summary == {}
    assert log.output_summary == {}


@pytest.mark.asyncio
async def test_run_tool_multiple_calls_append() -> None:
    """Test that multiple tool calls append to state.tool_calls."""
    state = GraphState(
        run_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )

    async def fake_call():
        return "result"

    # Make 3 calls
    await run_tool(name="tool.1", state=state, call=fake_call)
    await run_tool(name="tool.2", state=state, call=fake_call)
    await run_tool(name="tool.3", state=state, call=fake_call)

    # Verify all logged
    assert len(state.tool_calls) == 3
    assert state.tool_calls[0].name == "tool.1"
    assert state.tool_calls[1].name == "tool.2"
    assert state.tool_calls[2].name == "tool.3"
