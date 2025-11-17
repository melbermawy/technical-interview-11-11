#!/bin/bash
# Helper script to run Alembic migrations in development

set -e

if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL environment variable is not set"
    echo ""
    echo "Please set DATABASE_URL before running migrations:"
    echo ""
    echo "  For SQLite development:"
    echo "    export DATABASE_URL=\"sqlite+aiosqlite:///./dev.db\""
    echo ""
    echo "  For PostgreSQL:"
    echo "    export DATABASE_URL=\"postgresql+asyncpg://user:pass@localhost:5432/travel_planner\""
    echo ""
    exit 1
fi

echo "🔄 Running Alembic migrations..."
echo "📦 Database: $DATABASE_URL"
echo ""

alembic upgrade head

echo ""
echo "✅ Migrations completed successfully!"
