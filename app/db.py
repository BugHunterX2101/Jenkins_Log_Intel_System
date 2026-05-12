"""
Shared database configuration and session factory.

This module creates a SINGLE AsyncEngine instance that is shared across 
the entire application. All routers must use the get_session dependency
from this module to avoid creating redundant connection pools.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Global engine - created once at module import time.
# Keep the pool bounded so browser polling and webhook bursts cannot exhaust DB connections.
_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
)

# Global session factory
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database session.
    
    Usage:
        @router.get("/example")
        async def my_endpoint(session: AsyncSession = Depends(get_session)) -> dict:
            ...
    """
    async with _SessionFactory() as session:
        yield session


def get_engine():
    """Get the global engine instance."""
    return _engine


def get_session_factory():
    """Get the global session factory."""
    return _SessionFactory
