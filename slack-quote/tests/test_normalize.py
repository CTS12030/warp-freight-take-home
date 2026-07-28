from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.warp.normalize import normalize_rate_shop

FIXTURE = Path(__file__).resolve().parents[2] / "mock" / "fixtures" / "freight-quote.json"
QUOTED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _normalize(payload: dict | None = None):
    return normalize_rate_shop(payload or _load_fixture(), quoted_at=QUOTED_AT)


def test_sorted_cheapest_first():
    shop = _normalize()
    assert [o.option_id for o in shop.options] == [
        "opt_fwra",
        "opt_cnwy",
        "opt_rlca",
        "opt_ctbv",
        "opt_rlca_g",
        "opt_dolr",
        "opt_cnwy_g",
        "opt_utpa",
        "opt_xpol",
        "opt_wtch",
    ]


def test_transit_seconds_become_days():
    shop = _normalize()
    by_id = {o.option_id: o for o in shop.options}
    assert by_id["opt_fwra"].transit_days == 3.0
    assert by_id["opt_wtch"].transit_days == 4.5
    assert by_id["opt_cnwy"].transit_days == 5.0


def test_zero_transit_means_unknown():
    shop = _normalize()
    by_id = {o.option_id: o for o in shop.options}
    assert by_id["opt_utpa"].transit_days is None


def test_missing_service_level_stays_missing():
    shop = _normalize()
    by_id = {o.option_id: o for o in shop.options}
    assert by_id["opt_utpa"].service_level is None
    assert by_id["opt_cnwy_g"].service_level == "GUARANTEED"


def test_full_precision_preserved():
    shop = _normalize()
    by_id = {o.option_id: o for o in shop.options}
    assert by_id["opt_wtch"].rate == 760.572527


def test_request_id_extracted():
    shop = _normalize()
    assert shop.request_id == "01MOCKREQ0000000000000001"


def test_empty_lane():
    shop = normalize_rate_shop(
        {"id": "x", "requestId": "x", "options": []},
        quoted_at=QUOTED_AT,
    )
    assert shop.options == []
    assert shop.cheapest is None


def test_junk_options_skipped():
    payload = {
        "requestId": "x",
        "options": [
            {"id": "bad", "carrierName": "X", "carrierCode": "X", "source": "S"},
            {
                "id": "good",
                "carrierName": "Y",
                "carrierCode": "Y",
                "source": "S",
                "rate": 100.0,
            },
        ],
    }
    shop = normalize_rate_shop(payload, quoted_at=QUOTED_AT)
    assert [o.option_id for o in shop.options] == ["good"]


def test_tie_break():
    payload = {
        "requestId": "x",
        "options": [
            {
                "id": "b",
                "carrierName": "B",
                "carrierCode": "B",
                "source": "S",
                "rate": 100.0,
            },
            {
                "id": "a",
                "carrierName": "A",
                "carrierCode": "A",
                "source": "S",
                "rate": 100.0,
                "transitTime": 86400,
            },
        ],
    }
    shop = normalize_rate_shop(payload, quoted_at=QUOTED_AT)
    assert [o.option_id for o in shop.options] == ["a", "b"]
