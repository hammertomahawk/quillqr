from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from flask import current_app, g


def get_db() -> sqlite3.Connection:
    db = getattr(g, "_database", None)

    if db is None:
        db_path = current_app.config["DATABASE"]
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        g._database = db

    return db


def close_db(error: Exception | None = None) -> None:
    db = getattr(g, "_database", None)

    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()

    schema_path = Path(current_app.root_path) / "schema.sql"

    with schema_path.open("r", encoding="utf-8") as file:
        db.executescript(file.read())

    db.commit()


def query_one(
    sql: str,
    params: tuple[Any, ...] = (),
) -> sqlite3.Row | None:
    cursor = get_db().execute(sql, params)
    row = cursor.fetchone()
    cursor.close()
    return row


def execute(
    sql: str,
    params: tuple[Any, ...] = (),
) -> sqlite3.Cursor:
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor