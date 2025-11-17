"""Global pytest configuration."""

import os

# Set DATABASE_URL for tests before any imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
