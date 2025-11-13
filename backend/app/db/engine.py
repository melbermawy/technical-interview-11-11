"""Database engine and session factory."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings


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
