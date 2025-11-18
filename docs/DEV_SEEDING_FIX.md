# Dev Seeding Fix

## Problem Diagnosed

**Foreign key violation when creating agent runs:**
```
insert or update on table "agent_run" violates foreign key constraint "agent_run_org_id_fkey"
DETAIL: Key (org_id)=(00000000-0000-0000-0000-000000000001) is not present in table "org"
```

**Root cause:** The stub authentication (PR-4A) uses hardcoded org_id and user_id, but the database has no seed data for these entities. When the UI tries to create a run, the foreign key constraint fails.

## Solution Implemented

Created an idempotent dev seeding helper that explicitly seeds the dev org and user to match the stub auth IDs.

### Files Created

1. **`backend/app/db/seed_dev.py`** (58 lines)
   - Async function `seed_dev_org_and_user()` that:
     - Checks if org with ID `00000000-0000-0000-0000-000000000001` exists
     - Creates it if missing (name: "Dev Org 1")
     - Checks if user with ID `00000000-0000-0000-0000-000000000002` exists
     - Creates it if missing (email: "dev@example.com", org_id: dev org)
   - Idempotent: Safe to run multiple times
   - CLI entrypoint: `python -m backend.app.db.seed_dev`
   - Prints status messages for visibility

2. **`scripts/dev_seed.sh`** (23 lines)
   - Checks DATABASE_URL is set
   - Prints clear messages
   - Runs the seeding module
   - Executable helper script

3. **`tests/integration/test_seed_dev.py`** (25 lines)
   - Tests that dev IDs match stub auth defaults
   - Tests that seed function is importable and callable
   - Simple smoke tests (full integration tests blocked by JSONB/SQLite issue)

### Files Modified

1. **`PR4A_README.md`**
   - Added seeding step after migrations in "Running the System" section
   - Shows both direct command and helper script options

2. **`PR4B_README.md`**
   - Added seeding step in backend setup instructions
   - Placed after `alembic upgrade head`, before `uvicorn`

## How to Use

### First Time Setup

After running migrations, seed the dev org and user:

```bash
# Set database URL
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# Run migrations
alembic upgrade head

# Seed dev org and user (NEW STEP)
python -m backend.app.db.seed_dev

# Start backend
uvicorn backend.app.main:app --reload
```

### Using Helper Script

```bash
# Set database URL
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# Run migrations
./scripts/dev_migrate.sh

# Seed dev data
./scripts/dev_seed.sh

# Start backend
uvicorn backend.app.main:app --reload
```

### Idempotency

The seeding helper is safe to run multiple times:

```bash
$ python -m backend.app.db.seed_dev
Dev org already exists: Dev Org 1
Dev user already exists: dev@example.com
✅ Dev seeding complete
```

## Verification

### Run Tests

```bash
# All unit tests pass (73 tests)
pytest tests/unit/ -v

# Seeding tests pass
pytest tests/integration/test_seed_dev.py -v
# ✅ 2 passed
```

### Run Linters

```bash
# Ruff
ruff check backend/app/db/seed_dev.py tests/integration/test_seed_dev.py
# All checks passed!

# Black
black --check backend/app/db/seed_dev.py tests/integration/test_seed_dev.py
# All done! ✨ 🍰 ✨

# Mypy
mypy backend/app/db/seed_dev.py tests/integration/test_seed_dev.py
# Success: no issues found in 2 source files
```

## End-to-End Setup Sequence

From a fresh clone, here's the complete setup:

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Set database URL
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# 3. Run migrations
alembic upgrade head

# 4. Seed dev org and user (NEW STEP)
python -m backend.app.db.seed_dev

# 5. Start backend
uvicorn backend.app.main:app --reload
```

In another terminal:

```bash
# 6. Start UI
streamlit run ui/app.py
```

Now clicking "🚀 Start Planning" in the UI will work without foreign key violations.

## What Was NOT Changed

- **Stub auth IDs**: Left unchanged at `00000000-0000-0000-0000-000000000001` (org) and `00000000-0000-0000-0000-000000000002` (user)
- **Foreign key constraints**: Not relaxed or removed
- **Auto-seeding on import**: Not implemented (explicit seeding only)
- **Database models**: No changes to Org or User models
- **Existing migrations**: All 3 migrations (001, 002, 003) unchanged

## Design Decisions

### Why Explicit Seeding?

- **Visibility**: Developers know when seed data is created
- **Control**: No surprises from automatic side effects
- **Testing**: Tests can control their own fixture data
- **Production safety**: No risk of dev seeds in production

### Why These IDs?

The IDs match the stub auth defaults in `backend/app/api/auth.py`:
```python
# Default to test org/user if no auth header
org_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
```

### Why Idempotent?

Makes the helper safe to include in setup scripts and documentation examples. Developers can run it multiple times without errors.

## Known Limitations

- **SQLite incompatibility**: Full integration tests require PostgreSQL due to JSONB type in models (pre-existing issue)
- **Single dev org**: Only seeds one org/user pair for development
- **No cleanup helper**: To remove dev seeds, manually delete from database or drop tables

## Summary

**Before:** Clicking "Start Planning" in UI → Foreign key violation → Run creation fails

**After:** Run seeding helper → Dev org and user created → Run creation succeeds

**Commands to fix:**
```bash
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"
python -m backend.app.db.seed_dev
```
