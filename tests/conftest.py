"""Shared pytest fixtures for all test suites."""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.db.models import Base


@pytest_asyncio.fixture
async def postgres_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create async engine for PostgreSQL integration tests.

    Requires DATABASE_URL to be set to a real PostgreSQL connection string.
    Tests using this fixture should be marked with @pytest.mark.postgres.

    Usage:
        @pytest.mark.postgres
        async def test_something(postgres_engine):
            async with AsyncSession(postgres_engine) as session:
                # ... test code
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set - skipping postgres test")

    # Ensure it's a postgres URL
    if not database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
        pytest.skip(f"DATABASE_URL is not PostgreSQL: {database_url}")

    # Convert to async driver if needed
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        echo=False,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup: drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def postgres_session(postgres_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create async session for PostgreSQL integration tests.

    Usage:
        @pytest.mark.postgres
        async def test_something(postgres_session):
            result = await postgres_session.execute(...)
    """
    async with AsyncSession(postgres_engine) as session:
        yield session
        await session.rollback()
