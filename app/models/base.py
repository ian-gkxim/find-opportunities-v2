"""SQLAlchemy async engine setup and declarative base.

Provides the async engine, session factory, and declarative base class
for all ORM models in the application.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

    pass


def get_async_engine(database_url: str | None = None):
    """Create an async SQLAlchemy engine.

    Args:
        database_url: Database connection URL. If None, loads from settings.

    Returns:
        AsyncEngine configured for asyncpg.
    """
    if database_url is None:
        settings = get_settings()
        database_url = settings.database_url

    return create_async_engine(
        database_url,
        echo=False,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
    )


def get_async_session_factory(engine=None) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory.

    Args:
        engine: AsyncEngine instance. If None, creates one from settings.

    Returns:
        Configured async_sessionmaker for creating database sessions.
    """
    if engine is None:
        engine = get_async_engine()

    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
