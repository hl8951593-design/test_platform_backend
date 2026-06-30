from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _is_mysql_url(database_url: str) -> bool:
    return database_url.startswith("mysql://") or database_url.startswith("mysql+")


def _engine_kwargs(database_url: str) -> dict:
    kwargs = {
        "pool_pre_ping": settings.DB_POOL_PRE_PING,
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
    }
    if _is_mysql_url(database_url):
        kwargs.update(
            {
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
                "connect_args": {
                    "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
                },
            }
        )
    return kwargs


engine = create_engine(settings.DATABASE_URL, **_engine_kwargs(settings.DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def dispose_engine_after_disconnect() -> None:
    engine.dispose()
