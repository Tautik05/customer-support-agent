import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.config import settings

logger = logging.getLogger("support_agent.db")

Base = declarative_base()

async_db_url = settings.get_async_db_url()
connect_args = {}
engine_kwargs = {"echo": False}

if async_db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    engine_kwargs["connect_args"] = connect_args
else:
    # Neon Serverless Postgres with PgBouncer: NullPool is recommended for asyncpg
    engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(
    async_db_url,
    **engine_kwargs
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def init_db():
    """Initializes the database schema."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database schema initialized using: {async_db_url.split('@')[-1] if '@' in async_db_url else async_db_url}")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
