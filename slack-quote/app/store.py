"""SQLite-backed usage log for `/quote` commands."""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path

from app.models import QuoteLogEntry

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    slack_user_id TEXT NOT NULL,
    slack_user_name TEXT NOT NULL,
    slack_channel_id TEXT NOT NULL,
    slack_channel_name TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    outcome TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    origin_zip TEXT,
    dest_zip TEXT,
    pallets INTEGER,
    weight_lbs INTEGER,
    pickup_date TEXT,
    option_count INTEGER,
    cheapest_rate REAL,
    cheapest_carrier TEXT,
    request_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    response_json TEXT
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_quotes_ts ON quotes (ts)",
    "CREATE INDEX IF NOT EXISTS idx_quotes_lane ON quotes (origin_zip, dest_zip)",
    "CREATE INDEX IF NOT EXISTS idx_quotes_outcome ON quotes (outcome)",
)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path) -> None:
    with contextlib.closing(connect(path)) as conn:
        conn.execute(_CREATE_TABLE)
        for stmt in _INDEXES:
            conn.execute(stmt)
        conn.commit()


def log_quote(entry: QuoteLogEntry, *, path: Path) -> None:
    try:
        init_db(path)
        with contextlib.closing(connect(path)) as conn:
            conn.execute(
                """
                INSERT INTO quotes (
                    ts,
                    slack_user_id,
                    slack_user_name,
                    slack_channel_id,
                    slack_channel_name,
                    raw_text,
                    outcome,
                    latency_ms,
                    origin_zip,
                    dest_zip,
                    pallets,
                    weight_lbs,
                    pickup_date,
                    option_count,
                    cheapest_rate,
                    cheapest_carrier,
                    request_id,
                    attempts,
                    cache_hit,
                    error_code,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.ts.isoformat(),
                    entry.slack_user_id,
                    entry.slack_user_name,
                    entry.slack_channel_id,
                    entry.slack_channel_name,
                    entry.raw_text,
                    entry.outcome,
                    entry.latency_ms,
                    entry.origin_zip,
                    entry.dest_zip,
                    entry.pallets,
                    entry.weight_lbs,
                    entry.pickup_date.isoformat() if entry.pickup_date else None,
                    entry.option_count,
                    entry.cheapest_rate,
                    entry.cheapest_carrier,
                    entry.request_id,
                    entry.attempts,
                    1 if entry.cache_hit else 0,
                    entry.error_code,
                    json.dumps(entry.response_json, default=str)
                    if entry.response_json is not None
                    else None,
                ),
            )
            conn.commit()
    except (sqlite3.Error, OSError):
        # Never let a logging failure take down the request being logged.
        logger.exception("Failed to write quote log entry")
