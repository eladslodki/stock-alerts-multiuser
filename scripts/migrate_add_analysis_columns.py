#!/usr/bin/env python3
"""
Migration: Add analysis columns to fn_report_outputs.

Run once after deploying the Earnings Expectations & Market Reaction Engine:

    python scripts/migrate_add_analysis_columns.py

Safe to re-run — skips columns that already exist.
Supports both PostgreSQL and SQLite.
"""
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from fundamentals_db import engine   # noqa: E402 — must come after sys.path fix

NEW_COLUMNS = [
    # (column_name,  pg_type,  sqlite_type)
    ("consensus_json",        "JSONB", "TEXT"),
    ("surprise_json",         "JSONB", "TEXT"),
    ("market_analysis_json",  "JSONB", "TEXT"),
    ("narrative_change_json", "JSONB", "TEXT"),
]

TABLE = "fn_report_outputs"


def _existing_columns(conn) -> set:
    """Return the set of column names that already exist in TABLE."""
    is_sqlite = "sqlite" in str(engine.dialect.name).lower()

    if is_sqlite:
        rows = conn.execute(text(f"PRAGMA table_info({TABLE})")).fetchall()
        return {row[1] for row in rows}          # column 1 is "name"
    else:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :tbl"
            ),
            {"tbl": TABLE},
        ).fetchall()
        return {row[0] for row in rows}


def run_migration():
    is_sqlite = "sqlite" in str(engine.dialect.name).lower()

    with engine.begin() as conn:
        existing = _existing_columns(conn)
        added    = []
        skipped  = []

        for col_name, pg_type, sqlite_type in NEW_COLUMNS:
            if col_name in existing:
                skipped.append(col_name)
                continue

            col_type = sqlite_type if is_sqlite else pg_type

            if is_sqlite:
                # SQLite doesn't support IF NOT EXISTS on ALTER TABLE
                stmt = f"ALTER TABLE {TABLE} ADD COLUMN {col_name} {col_type}"
            else:
                stmt = (
                    f"ALTER TABLE {TABLE} "
                    f"ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                )

            conn.execute(text(stmt))
            added.append(col_name)

    print(f"Migration complete on: {engine.url}")
    if added:
        print(f"  Added   : {', '.join(added)}")
    if skipped:
        print(f"  Skipped : {', '.join(skipped)} (already existed)")


if __name__ == "__main__":
    run_migration()
