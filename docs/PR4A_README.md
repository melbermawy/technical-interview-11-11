# PR-4A: Orchestrator Skeleton + SSE Streaming

This PR implements the agent orchestration skeleton with run events and SSE streaming, as specified in the PR-4A requirements.

## What's Implemented

### 1. Run Events Model (`backend/app/models/events.py`)
- `RunEvent`: Typed event model with fields: `id`, `run_id`, `org_id`, `timestamp`, `sequence`, `node`, `phase`, `summary`, `payload`
- `SSERunEvent`: Lightweight SSE format for streaming
- Node names: `intent`, `planner`, `selector`, `tool_exec`, `verifier`, `repair`, `synth`, `responder`
- Phases: `started`, `completed`

### 2. Database Schema
- **Migration**: `003_add_run_events.py`
- **Table**: `run_event` with indexes on `(run_id, timestamp)` and `(run_id, sequence)`
- **Storage**: Postgres with full tenancy enforcement (`org_id` on every row)

### 3. Event Repository (`backend/app/db/run_events.py`)
- `append_run_event()`: Append new events with monotonic sequence
- `list_run_events()`: List events with optional `since_ts` filter, enforces tenancy

### 4. Graph Orchestrator (`backend/app/orchestration/`)
- **State model** (`state.py`): `GraphState` with run metadata, intent, plan, violations, decisions
- **Graph execution** (`graph.py`): `run_graph_stub()` executes 8 stub nodes in sequence:
  - All deterministic (no LLMs, no external APIs)
  - Emits events at each node start/completion
  - Creates minimal stub data (e.g., 4-day Paris plan with 2 activities)

### 5. API Endpoints (`backend/app/api/routes/runs.py`)

#### `POST /runs`
Creates a new agent run and starts graph execution in background.

**Request:**
```json
{
  "prompt": "Plan a trip to Paris",
  "max_days": 5,
  "budget_usd_cents": 250000
}
```

**Response (202 Accepted):**
```json
{
  "run_id": "uuid",
  "status": "accepted"
}
```

#### `GET /runs/{run_id}/events/stream`
Streams run events via Server-Sent Events (SSE).

**Query Parameters:**
- `last_ts` (optional): ISO8601 timestamp to resume from

**SSE Format:**
```
event: run_event
data: {"run_id": "...", "timestamp": "...", "sequence": 0, "node": "intent", "phase": "started", "summary": "..."}

event: heartbeat
data: {"ts": "2025-01-17T10:00:00Z"}

event: done
data: {"status": "succeeded"}
```

### 6. Auth Dependency (`backend/app/api/auth.py`)
Stub implementation for PR-4A:
- **No auth header**: Uses test defaults (org_id=00...01, user_id=00...02)
- **Bearer org_id:user_id**: Parses stub token format for testing
- **JWT tokens**: Returns 401 (real JWT validation will be in PR-10)

### 7. Async Database Support (`backend/app/db/engine.py`)
- `create_async_engine_from_settings()`: Creates async SQLAlchemy engine
- `get_session()`: FastAPI dependency for async sessions
- Converts `postgresql://` to `postgresql+asyncpg://` automatically

## Running the System

### Setup
```bash
# Install dependencies
pip install -e ".[dev]"

# Set database URL (required for migrations and app)
# For SQLite development:
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# Or for PostgreSQL:
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/travel_planner"

# Run migrations
alembic upgrade head
# Or use the helper script:
./scripts/dev_migrate.sh

# Seed dev org and user (required for stub auth)
python -m backend.app.db.seed_dev
# Or use the helper script:
./scripts/dev_seed.sh

# Start server
uvicorn backend.app.main:app --reload
```

**Note on Database URLs:**
- The app uses async drivers (`sqlite+aiosqlite://` or `postgresql+asyncpg://`)
- Alembic automatically converts these to sync equivalents (`sqlite://` or `postgresql://`)
- Both the app and migrations read from the same `DATABASE_URL` environment variable

### Test Run Creation
```bash
# Create a run (no auth required for testing)
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Plan a trip to Paris"}'

# Returns: {"run_id": "...", "status": "accepted"}
```

### Test SSE Streaming
```bash
# Stream events (replace {run_id} with actual ID)
curl -N http://localhost:8000/runs/{run_id}/events/stream

# You'll see:
# event: run_event
# data: {"run_id": "...", "sequence": 0, "node": "intent", ...}
# ...
# event: done
# data: {"status": "succeeded"}
```

### Test with Custom Org/User
```bash
# Create run with custom org/user
curl -X POST http://localhost:8000/runs \
  -H "Authorization: Bearer 12345678-1234-1234-1234-123456789012:87654321-4321-4321-4321-210987654321" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}'
```

## Testing

### Run All Tests
```bash
pytest tests/
```

### Run Specific Test Suites
```bash
# Graph execution and events
pytest tests/integration/test_orchestration.py

# API endpoints
pytest tests/integration/test_runs_api.py

# Auth module
pytest tests/unit/test_auth.py
```

### Test Coverage
- **Unit tests**:
  - `test_auth.py`: Auth dependency with various token formats
- **Integration tests**:
  - `test_orchestration.py`: Graph execution, event sequence, tenancy
  - `test_runs_api.py`: POST /runs, SSE streaming, auth enforcement

## Architecture Notes

### Event Sequence
Every run produces events in this order:
1. `intent` started/completed
2. `planner` started/completed
3. `selector` started/completed
4. `tool_exec` started/completed
5. `verifier` started/completed
6. (optional) `repair` started/completed
7. `synth` started/completed
8. `responder` started/completed

### Tenancy Enforcement
- All queries filter by `org_id`
- SSE endpoint returns 404 if run belongs to different org
- Events table has `org_id` column for isolation

### Background Execution
- Graph runs in `asyncio.create_task()` after POST returns 202
- Uses fresh DB session to avoid conflicts
- Errors are caught and stored in run status + events

## Trade-offs & Decisions

1. **Stub Auth**: For PR-4A, auth is minimal to enable testing without JWT setup. Real JWT validation will be added in PR-10.

2. **Polling SSE**: SSE endpoint polls DB every 500ms for new events (simple but works). A production system would use Redis pub/sub or similar for push-based notifications.

3. **In-memory vs Persistent**: All state is persisted to Postgres. No in-memory caching for PR-4A (keeps it simple and testable).

4. **Synchronous Graph**: Graph runs in a single async task, not distributed. Good enough for PR-4A scope (one destination, fixture data, fast execution).

5. **SQLite Tests**: Tests use in-memory SQLite for speed. Real integration tests against Postgres can be added later.

## What's NOT in This PR

- Real LLM calls (all stubs)
- Real external APIs (weather, flights, etc.)
- UI changes (Streamlit)
- JWT validation (stub only)
- Redis pub/sub for SSE (polling only)
- Distributed graph execution
- Real RAG / embeddings
- Tool adapters beyond stubs

## Next Steps (PR-4B and beyond)

- PR-4B: Streamlit UI to consume SSE stream and display progress
- PR-5: Real tool adapters (weather API, fixture data for others)
- PR-6: Real verifiers and repair logic
- PR-10: JWT auth implementation
- PR-11: Real LLM integration (intent extraction, planning, synthesis)
