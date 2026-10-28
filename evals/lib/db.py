"""SQLite helpers for script evals that need an isolated database."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import REPO_ROOT


DEFAULT_SCHEMA = REPO_ROOT / 'config' / 'schema.sql'


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
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    try:
        con = sqlite3.connect(db_path)
        con.executescript(schema.read_text())
        con.commit()
        con.close()
        yield db_path
    finally:
        os.unlink(db_path)
