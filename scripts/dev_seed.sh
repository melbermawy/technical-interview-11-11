#!/bin/bash
# Dev seeding script for PR-4A hotfix
# Seeds dev org and user for stub authentication
# Must be run from project root directory

set -e

# Check DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL environment variable not set"
    echo ""
    echo "Please set DATABASE_URL to your database connection string."
    echo ""
    echo "Examples:"
    echo "  export DATABASE_URL=\"sqlite+aiosqlite:///./dev.db\""
    echo "  export DATABASE_URL=\"postgresql+asyncpg://user:pass@localhost:5432/travel_planner\""
    echo ""
    exit 1
fi

echo "🌱 Seeding dev org and user for stub authentication..."
echo "DATABASE_URL: $DATABASE_URL"
echo ""

python -m backend.app.db.seed_dev

echo ""
echo "✅ Seeding complete - you can now use the stub auth tokens"
