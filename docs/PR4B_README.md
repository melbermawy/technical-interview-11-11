# PR-4B: Streamlit UI with SSE Streaming

This PR implements a minimal but complete Streamlit UI that connects to the PR-4A backend and displays real-time run progress via Server-Sent Events (SSE).

## What's Implemented

### 1. Streamlit Application (`ui/app.py`)

A 3-column layout showing:
- **Left column**: Activity feed with all run events as they arrive
- **Center column**: Itinerary view (stub for now, populated from events)
- **Right column**: Telemetry rail showing node progress, violations, and checks

Features:
- Real-time SSE streaming of run events
- Start new runs with custom trip brief, max days, and budget
- Live status updates with heartbeat tracking
- Clean, demo-ready UI suitable for interviews

### 2. Helper Module (`ui/helpers.py`)

Reusable logic for:
- `create_run()`: Call POST /runs to start new agent run
- `stream_run_events()`: SSE client that yields events from backend
- `build_activity_feed()`: Transform events into activity feed strings
- `build_itinerary_view()`: Extract itinerary from events
- `build_telemetry_view()`: Build checks/violations view

All helper functions have type hints and are unit-testable.

### 3. Tests (`tests/unit/test_ui_helpers.py`)

Unit tests for all view transformation functions:
- Activity feed building
- Itinerary extraction
- Telemetry/progress tracking

No Streamlit integration tests (out of scope for PR-4B).

## Running the System

### Prerequisites

```bash
# Install dependencies (if not already installed)
pip install -e ".[dev]"
```

### 1. Start the Backend

```bash
# Set database URL for development
export DATABASE_URL="postgresql://user:pass@localhost:5432/travel_planner"

# Or use SQLite for testing
export DATABASE_URL="sqlite+aiosqlite:///dev.db"

# Run migrations (first time only)
alembic upgrade head

# Seed dev org and user (required for stub auth)
python -m backend.app.db.seed_dev

# Start FastAPI backend
uvicorn backend.app.main:app --reload
```

Backend will be available at `http://localhost:8000`.

### 2. Start the Streamlit UI

In a separate terminal (from the project root):

```bash
# Must be run from project root directory
streamlit run ui/app.py
```

Streamlit will open in your browser at `http://localhost:8501`.

**Note on imports:** The `ui/app.py` file includes a sys.path shim at the top to ensure the `ui` package is importable when run via Streamlit. This is necessary because Streamlit executes the script as `__main__`, and the project root needs to be on the Python path for `from ui.helpers import ...` to work.

### 3. Use the UI

1. Enter a trip brief (e.g., "Plan a 3-day trip to Paris")
2. Adjust max days and budget if desired
3. Click "🚀 Start Planning"
4. Watch the activity feed populate in real-time as events stream in
5. See the itinerary and telemetry update as nodes complete

## Architecture

### SSE Streaming Flow

```
User clicks "Start Planning"
    ↓
UI calls POST /runs
    ↓
Backend returns run_id and starts graph in background
    ↓
UI opens SSE stream to GET /runs/{run_id}/events/stream
    ↓
Backend emits events as graph executes:
    - run_event: Node started/completed
    - heartbeat: Keep-alive signal
    - done: Run finished
    ↓
UI updates 3 columns in real-time
```

### Auth

For PR-4B, auth is hardcoded in `ui/helpers.py`:
- Org ID: `00000000-0000-0000-0000-000000000001`
- User ID: `00000000-0000-0000-0000-000000000002`

This matches the test defaults in the backend's stub auth (PR-4A).

**TODO(PR-10):** Replace with real JWT authentication.

### View Transformations

All view logic is in pure functions in `ui/helpers.py`:
- Input: List of event dicts
- Output: Structured data for UI columns
- Unit-testable without Streamlit

## Testing

### Run Unit Tests

```bash
# Run all tests
pytest tests/unit/test_ui_helpers.py -v

# Run with coverage
pytest tests/unit/test_ui_helpers.py --cov=ui --cov-report=term-missing
```

### Run Lint Checks

```bash
# Ruff
ruff check ui/

# Black
black --check ui/

# Mypy
mypy ui/
```

All checks should pass.

## What's NOT in This PR

- Real LLM integration (still stubbed in backend)
- Real tool execution (still stubbed)
- Authentication UI (hardcoded dev credentials)
- Reconnection logic for SSE (simple one-shot streaming)
- Full itinerary parsing (uses placeholder stub data)
- Historical run browsing (only shows current run)
- Multi-user/multi-org support in UI

## Next Steps

- **PR-5**: Real tool adapters (weather API, etc.)
- **PR-6**: Real verifiers and repair logic
- **PR-10**: JWT authentication UI
- **PR-11**: Real LLM integration for intent/planning/synthesis

## Demo Notes

This UI is **demo-ready** for technical interviews:
- End-to-end working system with real API calls
- Clean 3-column layout easy to explain
- Real-time updates demonstrate SSE streaming
- No mocks or fake data in the wiring (though backend is stubbed)

To demo:
1. Start backend + UI as shown above
2. Click "Start Planning" with sample trip brief
3. Point out the 3 columns updating in real-time
4. Explain that all data flows from real backend via SSE
5. Show how heartbeats keep connection alive
6. Note that backend logic is stubbed but wiring is production-ready
