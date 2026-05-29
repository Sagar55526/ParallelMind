from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(database_url, echo=echo, pool_size=10, max_overflow=20)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
