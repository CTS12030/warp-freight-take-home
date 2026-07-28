from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.store import connect


@dataclass(frozen=True)
class Report:
    days: int
    total: int
    per_day: list[tuple[str, int]]
    top_lanes: list[tuple[str, str, int]]
    no_rate_lanes: list[tuple[str, str, int]]
    outcome_counts: dict[str, int]
    upstream_failure_rate: float
    no_rate_rate: float
    cache_hit_rate: float
    avg_attempts: float
    latency_p50_ms: int
    latency_p95_ms: int


def _empty_report(days: int) -> Report:
    return Report(
        days=days,
        total=0,
        per_day=[],
        top_lanes=[],
        no_rate_lanes=[],
        outcome_counts={},
        upstream_failure_rate=0.0,
        no_rate_rate=0.0,
        cache_hit_rate=0.0,
        avg_attempts=0.0,
        latency_p50_ms=0,
        latency_p95_ms=0,
    )


def _percentile_nearest_rank(values: list[int], p: int) -> int:
    if not values:
        return 0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = math.ceil(p / 100 * n) - 1
    idx = max(0, min(idx, n - 1))
    return sorted_vals[idx]


def build_report(path: Path, *, days: int = 7, now: datetime | None = None) -> Report:
    if now is None:
        now = datetime.now(UTC)

    if not path.exists():
        return _empty_report(days)

    cutoff = (now - timedelta(days=days)).isoformat()

    try:
        with connect(path) as conn:
            rows = conn.execute(
                """
                SELECT ts, outcome, latency_ms, origin_zip, dest_zip, attempts, cache_hit
                FROM quotes
                WHERE ts >= ?
                """,
                (cutoff,),
            ).fetchall()
    except sqlite3.Error:
        return _empty_report(days)

    if not rows:
        return _empty_report(days)

    total = len(rows)

    per_day_counter: Counter[str] = Counter()
    lane_counter: Counter[tuple[str, str]] = Counter()
    no_rate_counter: Counter[tuple[str, str]] = Counter()
    outcome_counter: Counter[str] = Counter()
    ok_latencies: list[int] = []
    attempts_values: list[int] = []
    cache_hits = 0
    upstream_errors = 0
    no_rates = 0

    for row in rows:
        ts = row["ts"]
        per_day_counter[ts[:10]] += 1

        outcome = row["outcome"]
        outcome_counter[outcome] += 1

        if outcome == "upstream_error":
            upstream_errors += 1
        if outcome == "no_rates":
            no_rates += 1

        if row["cache_hit"]:
            cache_hits += 1

        attempts = row["attempts"]
        if attempts > 0:
            attempts_values.append(attempts)

        if outcome == "ok":
            ok_latencies.append(row["latency_ms"])

        origin = row["origin_zip"]
        dest = row["dest_zip"]
        if origin is not None and dest is not None:
            lane = (origin, dest)
            lane_counter[lane] += 1
            if outcome == "no_rates":
                no_rate_counter[lane] += 1

    per_day = sorted(per_day_counter.items(), key=lambda item: item[0])
    top_lanes = [
        (origin, dest, count)
        for (origin, dest), count in lane_counter.most_common()
    ]
    no_rate_lanes = [
        (origin, dest, count)
        for (origin, dest), count in no_rate_counter.most_common()
    ]

    avg_attempts = (
        sum(attempts_values) / len(attempts_values) if attempts_values else 0.0
    )

    return Report(
        days=days,
        total=total,
        per_day=per_day,
        top_lanes=top_lanes,
        no_rate_lanes=no_rate_lanes,
        outcome_counts=dict(outcome_counter),
        upstream_failure_rate=upstream_errors / total,
        no_rate_rate=no_rates / total,
        cache_hit_rate=cache_hits / total,
        avg_attempts=avg_attempts,
        latency_p50_ms=_percentile_nearest_rank(ok_latencies, 50),
        latency_p95_ms=_percentile_nearest_rank(ok_latencies, 95),
    )


def render_report(report: Report) -> str:
    lines: list[str] = []

    lines.append(f"Quote report (last {report.days} days)")
    lines.append("")

    if report.total == 0:
        lines.append("No data in the window.")
        return "\n".join(lines)

    lines.append("Volume")
    lines.append(f"  Total quotes: {report.total}")
    for day, count in report.per_day:
        lines.append(f"  {day}: {count}")
    lines.append("")

    lines.append("Top lanes")
    if report.top_lanes:
        for origin, dest, count in report.top_lanes:
            lines.append(f"  {origin} -> {dest}: {count}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("Lanes we could not price")
    if report.no_rate_lanes:
        for origin, dest, count in report.no_rate_lanes:
            lines.append(f"  {origin} -> {dest}: {count}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("Reliability")
    for outcome, count in sorted(report.outcome_counts.items()):
        lines.append(f"  {outcome}: {count}")
    lines.append(f"  Upstream failure rate: {report.upstream_failure_rate * 100:.1f}%")
    lines.append(f"  Average attempts: {report.avg_attempts:.1f}")
    lines.append(f"  Cache hit rate: {report.cache_hit_rate * 100:.1f}%")
    lines.append("")

    lines.append("Latency")
    lines.append(f"  p50: {report.latency_p50_ms} ms")
    lines.append(f"  p95: {report.latency_p95_ms} ms")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quote usage report")
    default_db = Path(__file__).resolve().parent.parent / "quotes.db"
    parser.add_argument("--db", type=Path, default=default_db)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    report = build_report(args.db, days=args.days)
    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
