from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from keyshop_bot.models import Base


def _ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url.removeprefix(prefix)
    if raw_path == ":memory:":
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> AsyncEngine:
    _ensure_sqlite_parent(database_url)
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name().startswith("sqlite"):
            for statement in (
                "ALTER TABLE accounts ADD COLUMN phone VARCHAR(40) NOT NULL DEFAULT ''",
                "ALTER TABLE accounts ADD COLUMN telegram_username VARCHAR(64) NOT NULL DEFAULT ''",
            ):
                try:
                    await conn.exec_driver_sql(statement)
                except OperationalError:
                    pass
