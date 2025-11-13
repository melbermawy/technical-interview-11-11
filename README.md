# Travel Planner - PR-1: Contracts & Foundations

This is the foundation PR for the agentic travel planner system. It establishes type-safe contracts, configuration, validation, and CI infrastructure.

## Overview

PR-1 delivers:
- Pydantic v2 models for all core contracts (Intent, Plan, Itinerary, tool results)
- Typed settings with single source of truth
- JSON schema export for PlanV1 and ItineraryV1
- Comprehensive validation tests
- Eval skeleton with stub scenarios
- CI pipeline (ruff, black, mypy, pytest)

## Requirements

- Python 3.11+
- pip

## Development Setup

### 1. Clone and Install

```bash
git clone <repo-url>
cd technical-interview-11-11
pip install -e ".[dev]"
```

### 2. Set Up Pre-commit Hooks

```bash
pre-commit install
```

### 3. Run Tests

```bash
# Run all tests
pytest -q

# Run specific test suites
pytest tests/unit/
pytest tests/eval/
```

### 4. Export Schemas

```bash
python scripts/export_schemas.py
```

This creates:
- `docs/schemas/PlanV1.schema.json`
- `docs/schemas/ItineraryV1.schema.json`

### 5. Run Eval

```bash
python eval/runner.py
```

## Project Structure

```
.
├── backend/
│   └── app/
│       ├── config.py              # Typed settings
│       └── models/
│           ├── common.py          # Geo, TimeWindow, Money, enums, Provenance
│           ├── intent.py          # IntentV1, DateWindow, Preferences
│           ├── plan.py            # PlanV1, DayPlan, Slot, Choice
│           ├── tool_results.py    # FlightOption, Lodging, Attraction, etc.
│           ├── violations.py      # Violation
│           ├── itinerary.py       # ItineraryV1
│           └── __init__.py        # Re-exports
├── docs/
│   ├── SPEC.md                    # System specification (read-only)
│   └── schemas/                   # Generated JSON schemas
├── eval/
│   ├── scenarios.yaml             # Eval scenarios
│   └── runner.py                  # Eval runner
├── scripts/
│   └── export_schemas.py          # Schema export script
├── tests/
│   ├── unit/
│   │   ├── test_contracts_validators.py
│   │   ├── test_tri_state_serialization.py
│   │   ├── test_jsonschema_roundtrip.py
│   │   ├── test_constants_single_source.py
│   │   └── test_nonoverlap_property.py
│   └── eval/
│       └── test_eval_runner.py
├── .github/
│   └── workflows/
│       └── ci.yml                 # CI pipeline
├── .env.example                   # Environment variables template
├── pyproject.toml                 # Dependencies and build config
├── ruff.toml                      # Ruff linter config
├── mypy.ini                       # Mypy type checker config (strict mode)
├── pytest.ini                     # Pytest config
└── .pre-commit-config.yaml        # Pre-commit hooks
```

## Key Contracts

### IntentV1
User input for trip planning. Validates:
- `date_window.start <= date_window.end`
- `budget_usd_cents > 0`
- At least one airport

### PlanV1
Generated plan with ranked choices. Validates:
- 4-7 days
- Non-overlapping slots per day
- `choices[0]` is the selected option

### ItineraryV1
Final output for user. Includes:
- Cost breakdown by category
- Decisions with rationale
- Citations with provenance

### Tri-State Booleans
`indoor` and `kid_friendly` fields support `True | False | None`:
- `True`: explicitly indoor/kid-friendly
- `False`: explicitly outdoor/not kid-friendly
- `None`: unknown or mixed

## CI Pipeline

The CI pipeline runs on every push and PR:

1. **Linting**: `ruff check .`
2. **Formatting**: `black --check .`
3. **Type checking**: `mypy backend/ eval/ scripts/` (strict mode)
4. **Tests**: `pytest -q`
5. **Schema export**: Verifies schemas are generated
6. **Eval**: Runs stub scenarios

## Running CI Locally

```bash
# Lint
ruff check .

# Format
black --check .

# Type check
mypy backend/ eval/ scripts/

# Test
pytest -q

# Export schemas
python scripts/export_schemas.py

# Run eval
python eval/runner.py
```

## Configuration

All settings are in [backend/app/config.py](backend/app/config.py). Values are loaded from environment variables or `.env` file.

See [.env.example](.env.example) for all available settings.

## Testing

### Unit Tests
- **Validators**: Test contract invariants (reversed dates, empty airports, overlapping slots, etc.)
- **Tri-state serialization**: Ensure `indoor` and `kid_friendly` round-trip correctly
- **JSON schema**: Verify exported schemas validate correct payloads
- **Constants**: Ensure settings are accessible and not duplicated
- **Non-overlap property**: Property-based tests with random seeds

### Eval Tests
- **Scenario execution**: Verify eval runner runs without errors
- **Pass/fail reporting**: Ensure scenarios report expected results

## Design Decisions

### Tri-State Booleans
Per SPEC.md, `indoor` and `kid_friendly` are `bool | None` to represent unknown state. This allows the selector to handle uncertainty (e.g., prefer indoor when weather is bad, but don't block if unknown).

### Money as Integer Cents
All monetary amounts are stored as `int` cents to avoid floating-point rounding errors. Display layer formats to dollars.

### Enums as Lowercase Snake Case
Per SPEC.md canonicalization rules, all enums use `lowercase_snake_case` (e.g., `kid_friendly`, `budget_exceeded`).

### Validators in Models
Pydantic validators enforce invariants:
- `DateWindow`: `end >= start`
- `IntentV1`: `budget > 0`, `len(airports) >= 1`
- `DayPlan`: Non-overlapping slots
- `PlanV1`: 4-7 days

### No Business Logic
This PR contains **only contracts and validators**. No HTTP routes, no database, no tools, no LLM integration. Those come in later PRs.

## Next Steps (Future PRs)

- PR-2: Tool adapters (weather, fixtures)
- PR-3: LangGraph orchestrator
- PR-4: Verifiers and repair
- PR-5: FastAPI routes and SSE streaming
- PR-6: Postgres + Redis integration
- PR-7: Streamlit UI

## Compliance

✅ All contracts match SPEC.md
✅ Tri-state fields tested (`indoor`, `kid_friendly`)
✅ Validators enforce invariants
✅ Enums are lowercase snake_case
✅ Money stored as int cents
✅ No `Any` types except `Violation.details`
✅ No global mutable state
✅ CI enforces ruff, black, mypy --strict, pytest
✅ JSON schemas exported
✅ Eval runner produces pass/fail on stub scenarios

## License

Proprietary - Technical Interview Project
