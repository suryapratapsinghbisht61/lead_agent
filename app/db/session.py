"""Database connection. DATABASE_URL decides where data lives:
  sqlite:///data/leads.db   (default, a single local file)
  postgresql://user:pass@host/db   (later; also needs `uv add psycopg[binary]`)
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # make sure the folder for the .db file exists
        Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
        # API, worker and dashboard may use the DB from different threads
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, connect_args=connect_args)


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call many times."""
    from app.db import models  # noqa: F401  (import registers the tables)

    SQLModel.metadata.create_all(get_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
