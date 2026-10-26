from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

is_sqlite = settings.DATABASE_URL.startswith("sqlite")
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
    "future": True,
}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 1800,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)


async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base model for SQLAlchemy declarative mapping."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for asynchronous database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_health() -> bool:
    """Check connectivity to PostgreSQL database."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    """Dispose database engine connections."""
    await engine.dispose()
