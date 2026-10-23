"""SQLite helpers for script evals that need an isolated database."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import REPO_ROOT

DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.sql"


@contextmanager
def temp_db(schema: Path | None = None) -> Iterator[str]:
    """Yield a path to a fresh SQLite DB with the app schema applied.

    Cleans up the file on exit.

    Usage:
        with temp_db() as db_path:
            seed_data(db_path)
            result = run_script(db_path, ...)
    """
    schema = schema or DEFAULT_SCHEMA
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        con = sqlite3.connect(db_path)
        con.executescript(schema.read_text())
        con.commit()
        con.close()
        yield db_path
    finally:
        os.unlink(db_path)


def seed_categories(db_path: str, categories: list[tuple[str, str]] | None = None) -> None:
    """Insert the default category list into the categories table."""
    now = "2026-01-01T00:00:00+00:00"
    rows = categories or [
        ("food",          "Food & Dining"),
        ("transport",     "Transport"),
        ("entertainment", "Entertainment"),
        ("health",        "Health"),
        ("shopping",      "Shopping"),
        ("services",      "Services & Utilities"),
        ("transfers",     "Transfers"),
        ("cash",          "Cash Withdrawal"),
        ("other",         "Other"),
    ]
    con = sqlite3.connect(db_path)
    with con:
        for slug, label in rows:
            con.execute(
                "INSERT OR IGNORE INTO categories (slug, label, created_at) VALUES (?, ?, ?)",
                (slug, label, now),
            )
    con.close()
