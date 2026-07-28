from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.models import QuoteLogEntry
from app.store import log_quote
from scripts.report import build_report, render_report


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


NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


def test_empty_database(tmp_path: Path) -> None:
    report = build_report(tmp_path / "missing.db", now=NOW)
    assert report.total == 0
    rendered = render_report(report)
    assert rendered
    assert "No data" in rendered


def test_volume_and_lanes(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    recent = NOW - timedelta(days=3)
    old = NOW - timedelta(days=30)

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
        _entry(ts=old, origin_zip="10001", dest_zip="20001"),
        path=db,
    )

    report = build_report(db, days=7, now=NOW)
    assert report.total == 5
    assert report.top_lanes == [("90001", "60601", 3), ("30301", "33101", 2)]


def test_no_rate_lanes(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    for _ in range(2):
        log_quote(
            _entry(
                ts=ts,
                outcome="no_rates",
                origin_zip="00501",
                dest_zip="60601",
            ),
            path=db,
        )
    log_quote(
        _entry(ts=ts, outcome="ok", origin_zip="90001", dest_zip="60601"),
        path=db,
    )

    report = build_report(db, days=7, now=NOW)
    assert report.no_rate_lanes == [("00501", "60601", 2)]
    assert report.no_rate_rate == pytest.approx(2 / 3)


def test_upstream_failure_rate(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    log_quote(_entry(ts=ts, outcome="upstream_error"), path=db)
    for _ in range(3):
        log_quote(_entry(ts=ts, outcome="ok"), path=db)

    report = build_report(db, days=7, now=NOW)
    assert report.outcome_counts == {"ok": 3, "upstream_error": 1}
    assert report.upstream_failure_rate == pytest.approx(0.25)


def test_latency_percentiles(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    for latency in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
        log_quote(
            _entry(ts=ts, outcome="ok", latency_ms=latency),
            path=db,
        )

    report = build_report(db, days=7, now=NOW)
    assert report.latency_p50_ms == 500
    assert report.latency_p95_ms == 1000


def test_latency_ignores_non_ok_rows(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    for latency in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
        log_quote(
            _entry(ts=ts, outcome="ok", latency_ms=latency),
            path=db,
        )
    log_quote(
        _entry(ts=ts, outcome="upstream_error", latency_ms=45000),
        path=db,
    )

    report = build_report(db, days=7, now=NOW)
    assert report.latency_p95_ms == 1000


def test_cache_hit_rate(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    log_quote(_entry(ts=ts, cache_hit=True), path=db)
    for _ in range(3):
        log_quote(_entry(ts=ts, cache_hit=False), path=db)

    report = build_report(db, days=7, now=NOW)
    assert report.cache_hit_rate == pytest.approx(0.25)


def test_rows_without_lane_counted_not_grouped(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    for _ in range(2):
        log_quote(
            _entry(
                ts=ts,
                outcome="invalid_input",
                origin_zip=None,
                dest_zip=None,
            ),
            path=db,
        )
    log_quote(
        _entry(ts=ts, outcome="ok", origin_zip="90001", dest_zip="60601"),
        path=db,
    )

    report = build_report(db, days=7, now=NOW)
    assert report.total == 3
    assert len(report.top_lanes) == 1


def test_per_day_oldest_first(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"

    log_quote(_entry(ts=NOW - timedelta(days=6)), path=db)
    log_quote(_entry(ts=NOW - timedelta(days=3)), path=db)
    log_quote(_entry(ts=NOW - timedelta(days=1)), path=db)

    report = build_report(db, days=7, now=NOW)
    dates = [day for day, _ in report.per_day]
    assert dates == sorted(dates)
    assert len(dates) == 3


def test_render_report_includes_headline_numbers(tmp_path: Path) -> None:
    db = tmp_path / "quotes.db"
    ts = NOW - timedelta(days=1)

    log_quote(
        _entry(ts=ts, origin_zip="90001", dest_zip="60601"),
        path=db,
    )

    report = build_report(db, days=7, now=NOW)
    rendered = render_report(report)
    assert str(report.total) in rendered
    assert "90001 -> 60601" in rendered
