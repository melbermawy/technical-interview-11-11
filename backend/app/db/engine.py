"""Database engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings, get_settings


def create_engine_from_settings(settings: Settings) -> Engine:
    """Create SQLAlchemy engine from settings.

    Raises:
        ValueError: If DATABASE_URL is unset or empty.
    """
    database_url = settings.database_url or settings.postgres_url

    if not database_url or database_url == "postgresql://user:pass@localhost:5432/travel_planner":
        raise ValueError(
            "DATABASE_URL must be set to a valid connection string. "
            "Please configure the database_url setting."
        )

    return create_engine(database_url, pool_pre_ping=True, echo=False)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessionmaker for creating database sessions.

    Args:
        engine: SQLAlchemy engine

    Returns:
        Sessionmaker bound to the engine
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_async_engine_from_settings(settings: Settings) -> AsyncEngine:
    """Create async SQLAlchemy engine from settings.

    Raises:
        ValueError: If DATABASE_URL is unset or empty.
    """
    database_url = settings.database_url or settings.postgres_url

    if not database_url or database_url == "postgresql://user:pass@localhost:5432/travel_planner":
        raise ValueError(
            "DATABASE_URL must be set to a valid connection string. "
            "Please configure the database_url setting."
        )

    # Convert postgresql:// to postgresql+asyncpg://
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return create_async_engine(database_url, pool_pre_ping=True, echo=False)


# Global async engine for PR-4A
_async_engine: AsyncEngine | None = None


def get_async_engine() -> AsyncEngine:
    """Get global async engine instance."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine_from_settings(get_settings())
    return _async_engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session.

    Yields:
        AsyncSession instance
    """
    async with AsyncSession(get_async_engine()) as session:
        yield session
