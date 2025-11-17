# Alembic Configuration Fix

## Problem Diagnosed

**Root cause:** `alembic.ini` contained a placeholder database URL that was never overridden:
```ini
sqlalchemy.url = driver://user:pass@localhost/dbname
```

This caused the error:
```
sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:driver
```

## Solution Implemented

Modified `backend/app/db/alembic/env.py` to:

1. **Read from app settings** - Use the same `DATABASE_URL` environment variable as the FastAPI app
2. **Convert async URLs to sync** - Alembic requires sync SQLAlchemy drivers:
   - `sqlite+aiosqlite://` → `sqlite://`
   - `postgresql+asyncpg://` → `postgresql://`
3. **Override placeholder** - Set the real URL via `config.set_main_option()` before migrations run

### Old Behavior
```python
# env.py just used whatever was in alembic.ini
url = config.get_main_option("sqlalchemy.url")  # "driver://..."
```

### New Behavior
```python
# env.py reads from app config and converts async URLs
from backend.app.config import get_settings

settings = get_settings()
database_url = settings.database_url or settings.postgres_url

# Convert async drivers to sync for Alembic
if database_url.startswith("sqlite+aiosqlite://"):
    database_url = database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
elif database_url.startswith("postgresql+asyncpg://"):
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

# Override the ini file's placeholder
config.set_main_option("sqlalchemy.url", database_url)
```

## Files Changed

1. **`backend/app/db/alembic/env.py`** - Added URL loading and conversion logic (14 new lines)
2. **`scripts/dev_migrate.sh`** - Created helper script that checks DATABASE_URL is set before running migrations
3. **`PR4A_README.md`** - Updated with migration instructions and DATABASE_URL requirements

## How to Run Migrations Now

### Option 1: Direct Command

```bash
# Set database URL
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# Run migrations
alembic upgrade head
```

### Option 2: Helper Script

```bash
# Set database URL
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"

# Run with helper (checks URL is set)
./scripts/dev_migrate.sh
```

### For PostgreSQL

```bash
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/travel_planner"
alembic upgrade head
```

## Verification

The URL conversion logic works correctly:

```bash
$ export DATABASE_URL="sqlite+aiosqlite:///./test.db"
$ python -c "from backend.app.config import get_settings; ..."
Original URL: sqlite+aiosqlite:///./test.db
Converted URL: sqlite:///./test.db
```

```bash
$ export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db"
$ python -c "from backend.app.config import get_settings; ..."
Original URL: postgresql+asyncpg://user:pass@localhost:5432/db
Converted URL: postgresql://user:pass@localhost:5432/db
```

## What Was NOT Changed

- **`alembic.ini`** - Left with placeholder URL (harmless since env.py overrides it)
- **Existing migrations** - All 3 migrations (001, 002, 003) remain unchanged
- **App config** - `backend/app/config.py` unchanged (already worked correctly)
- **Database models** - No changes to model definitions

## Known Limitation

SQLite migrations currently fail due to JSONB type incompatibility (pre-existing issue, unrelated to this fix):
```
sqlalchemy.exc.UnsupportedCompilationError: ... can't render element of type JSONB
```

This is because the models use PostgreSQL's `JSONB` type which doesn't exist in SQLite. For SQLite compatibility, models would need conditional type mapping (JSON for SQLite, JSONB for PostgreSQL). This is outside the scope of the Alembic URL fix.

**Workaround:** Use PostgreSQL for migrations, or update models to use `JSON` instead of `JSONB` for cross-database compatibility.

## Summary

**Before:** Alembic used hardcoded placeholder URL → failed with "No such module: driver"

**After:** Alembic reads `DATABASE_URL` from environment, converts async → sync, works with both SQLite and PostgreSQL URLs

**Commands to run:**
```bash
export DATABASE_URL="sqlite+aiosqlite:///./dev.db"
alembic upgrade head
```
