"""Shared SQLAlchemy engine + small helpers for the ETL layer."""
import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from config import POSTGRES_DSN  # noqa: E402

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(POSTGRES_DSN, pool_pre_ping=True)
    return _engine
