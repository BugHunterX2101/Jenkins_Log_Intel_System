"""
Shared database configuration and session factory.

This module creates a SINGLE AsyncEngine instance that is shared across 
the entire application. All routers must use the get_session dependency
from this module to avoid creating redundant connection pools.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# Global engine - created once at module import time
_engine = create_async_engine(settings.DATABASE_URL, echo=False)

# Global session factory
_SessionFactory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
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
