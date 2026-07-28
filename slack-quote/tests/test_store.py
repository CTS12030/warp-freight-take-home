"""Tests for the SQLite usage log."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.models import QuoteLogEntry
from app.store import connect, init_db, log_quote


def _entry(**overrides: Any) -> QuoteLogEntry:
    defaults: dict[str, Any] = {
        "ts": datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC),
        "slack_user_id": "U123",
        "slack_user_name": "alice",
        "slack_channel_id": "C456",
        "slack_channel_name": "freight",
        "raw_text": "90001 60601 2 5000",
        "outcome": "ok",
        "latency_ms": 100,
    }
    defaults.update(overrides)
    return QuoteLogEntry(**defaults)


def _fetch_one(path: Path) -> dict[str, Any]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM quotes LIMIT 1").fetchone()
    assert row is not None
    return dict(row)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    init_db(db)
    init_db(db)
    with connect(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'quotes'"
        ).fetchone()
    assert row is not None
    assert row["name"] == "quotes"


def test_successful_quote_round_trips(tmp_path: Path) -> None:
    entry = _entry(
        outcome="ok",
        origin_zip="90001",
        dest_zip="60601",
        option_count=10,
        cheapest_rate=432.288,
        cheapest_carrier="Forward Air",
        attempts=2,
        latency_ms=8123,
    )
    log_quote(entry, path=tmp_path / "quotes.db")

    row = _fetch_one(tmp_path / "quotes.db")
    assert row["outcome"] == "ok"
    assert row["origin_zip"] == "90001"
    assert row["dest_zip"] == "60601"
    assert row["option_count"] == 10
    assert isinstance(row["cheapest_rate"], float)
    assert row["cheapest_rate"] == 432.288
    assert row["cheapest_carrier"] == "Forward Air"
    assert row["attempts"] == 2
    assert row["latency_ms"] == 8123


def test_failure_logged_as_fully_as_success(tmp_path: Path) -> None:
    entry = _entry(
        outcome="upstream_error",
        error_code="upstream_unavailable",
        attempts=3,
        option_count=None,
        cheapest_rate=None,
    )
    log_quote(entry, path=tmp_path / "quotes.db")

    row = _fetch_one(tmp_path / "quotes.db")
    assert row["outcome"] == "upstream_error"
    assert row["error_code"] == "upstream_unavailable"
    assert row["attempts"] == 3
    assert row["option_count"] is None
    assert row["cheapest_rate"] is None


def test_unparseable_command_logged_with_no_lane(tmp_path: Path) -> None:
    entry = _entry(
        outcome="invalid_input",
        origin_zip=None,
        dest_zip=None,
    )
    log_quote(entry, path=tmp_path / "quotes.db")

    row = _fetch_one(tmp_path / "quotes.db")
    assert row["outcome"] == "invalid_input"
    assert row["origin_zip"] is None
    assert row["dest_zip"] is None


def test_cache_hit_stored_as_zero_or_one(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    log_quote(_entry(cache_hit=True), path=db)
    log_quote(_entry(cache_hit=False), path=db)

    with connect(db) as conn:
        rows = conn.execute(
            "SELECT cache_hit FROM quotes ORDER BY id"
        ).fetchall()
    assert [row["cache_hit"] for row in rows] == [1, 0]


def test_response_json_round_trips(tmp_path: Path) -> None:
    payload = {"options": [{"rate": 1.5}]}
    log_quote(_entry(response_json=payload), path=tmp_path / "quotes.db")

    row = _fetch_one(tmp_path / "quotes.db")
    assert json.loads(row["response_json"]) == payload


def test_answers_how_many_quotes_this_week_by_lane(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    now = datetime.now(tz=UTC)
    recent = now - timedelta(days=3)
    old = now - timedelta(days=30)

    for _ in range(3):
        log_quote(
            _entry(ts=recent, origin_zip="90001", dest_zip="60601"),
            path=db,
        )
    for _ in range(2):
        log_quote(
            _entry(ts=recent, origin_zip="30301", dest_zip="33101"),
            path=db,
        )
    log_quote(
        _entry(ts=old, origin_zip="90001", dest_zip="60601"),
        path=db,
    )

    cutoff = (now - timedelta(days=7)).isoformat()
    with connect(db) as conn:
        rows = conn.execute(
            """
            SELECT origin_zip, dest_zip, COUNT(*) AS cnt
            FROM quotes
            WHERE ts >= ?
            GROUP BY origin_zip, dest_zip
            ORDER BY cnt DESC
            """,
            (cutoff,),
        ).fetchall()

    assert [(row["origin_zip"], row["dest_zip"], row["cnt"]) for row in rows] == [
        ("90001", "60601", 3),
        ("30301", "33101", 2),
    ]


def test_logging_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    bad_path = blocker / "quotes.db"

    log_quote(_entry(), path=bad_path)
