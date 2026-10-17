"""Async SQLAlchemy engine and session factory.

A single ``get_db`` async generator is used as a FastAPI dependency to
provide a session-per-request with automatic rollback on failure.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kairos_kb.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; rollback on exception, always close."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
