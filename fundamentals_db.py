"""
SQLAlchemy engine and session management for the Fundamentals Reports feature.
Isolated from the existing raw-psycopg2 database layer.
"""
import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger(__name__)

# Reuse DATABASE_URL already consumed by the rest of the app.
# Fall back to a local SQLite file for convenience during local dev.
_raw_url = os.getenv("DATABASE_URL", "sqlite:///fundamentals.db")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

FUNDAMENTALS_DATABASE_URL = _raw_url

engine = create_engine(
    FUNDAMENTALS_DATABASE_URL,
    pool_pre_ping=True,
    # SQLite needs this for multi-thread Flask dev server
    connect_args={"check_same_thread": False} if "sqlite" in FUNDAMENTALS_DATABASE_URL else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def get_db():
    """Yield a transactional SQLAlchemy session, committing on success."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all fundamentals tables if they don't already exist."""
    # Import models here so Base.metadata is populated before create_all.
    from fundamentals_models import Company, Filing, FilingText, ReportOutput  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Fundamentals DB tables ensured.")
