from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from eiraos.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Alias for compatibility with code referencing AsyncSessionLocal
AsyncSessionLocal = async_session_maker

Base = declarative_base()

async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
