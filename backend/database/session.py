
"""Engine, session factory and declarative base. PostgreSQL only."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.core.config import get_settings


class Base(DeclarativeBase):
    pass


# Cached database engine and session factory
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    engine = create_engine(url, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal

    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(
            bind=_engine,
            expire_on_commit=False
        )

    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine() -> None:
    """Drop cached engine (used by tests and the reset script)."""
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _SessionLocal = None


@contextmanager
def session_scope(factory=None):
    """Transactional scope: commit on success, roll back on any error."""
    session = (factory or get_session_factory())()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency (one session per request)."""
    session = get_session_factory()()

    try:
        yield session
    finally:
        session.close()
