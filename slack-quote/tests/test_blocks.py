from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.models import Lane, ParsedQuote, WarpError
from app.slack.blocks import (
    expired_card_blocks,
    format_money,
    format_service_level,
    format_transit,
    no_rates_blocks,
    quote_card_blocks,
    quote_error_blocks,
)
from app.warp.normalize import normalize_rate_shop

FIXTURE = Path(__file__).resolve().parents[2] / "mock" / "fixtures" / "freight-quote.json"
QUOTED_AT = datetime(2026, 7, 28, 19, 34, tzinfo=timezone.utc)
TOKEN = "test-token-abc"


def all_text(blocks: list[dict]) -> str:
    parts: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(blocks)
    return " ".join(parts)


def _load_shop():
    payload = json.loads(FIXTURE.read_text())
    return normalize_rate_shop(payload, quoted_at=QUOTED_AT)


def _sample_parsed(**overrides) -> ParsedQuote:
    defaults = dict(
        lane=Lane(origin_zip="90001", dest_zip="60601"),
        pallets=2,
        weight_lbs=1000,
        pickup_date=date(2026, 7, 29),
    )
    defaults.update(overrides)
    return ParsedQuote(**defaults)


def _rate_section_text(blocks: list[dict]) -> str:
    for block in blocks:
        if block.get("type") == "section":
            text = block["text"]["text"]
            if "`1`" in text:
                return text
    raise AssertionError("rate section not found")


def _action_ids(blocks: list[dict]) -> set[str]:
    ids: set[str] = set()
    for block in blocks:
        if block.get("type") == "actions":
            for element in block.get("elements", []):
                if action_id := element.get("action_id"):
                    ids.add(action_id)
    return ids


def _button_values(blocks: list[dict]) -> list[str]:
    values: list[str] = []
    for block in blocks:
        if block.get("type") == "actions":
            for element in block.get("elements", []):
                if value := element.get("value"):
                    values.append(value)
    return values


def test_format_money():
    assert format_money(432.288) == "$432.29"
    assert format_money(1234.5) == "$1,234.50"
    assert format_money(760.572527) == "$760.57"


def test_format_transit():
    assert format_transit(None) == "transit n/a"
    assert format_transit(1.0) == "1 day"
    assert format_transit(3.0) == "3 days"
    assert format_transit(4.5) == "4.5 days"


def test_format_service_level():
    assert format_service_level(None) == "service level unspecified"
    assert format_service_level("GUARANTEED") == "GUARANTEED"


def test_default_card_shows_three_rows():
    blocks = quote_card_blocks(_sample_parsed(), _load_shop(), token=TOKEN)
    text = _rate_section_text(blocks)
    lines = [line for line in text.split("\n") if line.strip()]
    assert len(lines) == 3
    assert "Forward Air" in lines[0]
    assert "$432.29" in lines[0]
    assert "Showing the 3 cheapest of 10." in all_text(blocks)


def test_show_all_shows_ten_rows():
    blocks = quote_card_blocks(
        _sample_parsed(), _load_shop(), token=TOKEN, show_all=True
    )
    text = _rate_section_text(blocks)
    lines = [line for line in text.split("\n") if line.strip()]
    assert len(lines) == 10
    assert "show_all_rates" not in _action_ids(blocks)


def test_buttons():
    blocks = quote_card_blocks(_sample_parsed(), _load_shop(), token=TOKEN)
    assert _action_ids(blocks) == {"show_all_rates", "share_quote"}
    assert all(v == TOKEN for v in _button_values(blocks))


def test_footer():
    blocks = quote_card_blocks(_sample_parsed(), _load_shop(), token=TOKEN)
    text = all_text(blocks)
    assert "Indicative rate, not a booking" in text
    assert "10 carriers" in text
    assert "req 01MOCKREQ0000000000000001" in text


def test_cache_label():
    cached = quote_card_blocks(
        _sample_parsed(), _load_shop(), token=TOKEN, cache_hit=True
    )
    uncached = quote_card_blocks(
        _sample_parsed(), _load_shop(), token=TOKEN, cache_hit=False
    )
    assert "cached" in all_text(cached)
    assert "cached" not in all_text(uncached)


def test_assumptions_surfaced():
    parsed = _sample_parsed(assumptions=["Assumed 1 pallet (none specified)."])
    blocks = quote_card_blocks(parsed, _load_shop(), token=TOKEN)
    assert "Assumed 1 pallet (none specified)." in all_text(blocks)


def test_none_never_leaks():
    shop = _load_shop()
    parsed = _sample_parsed()
    cases = [
        quote_card_blocks(parsed, shop, token=TOKEN),
        quote_card_blocks(parsed, shop, token=TOKEN, show_all=True),
        no_rates_blocks(parsed),
        quote_error_blocks(
            parsed,
            WarpError("upstream_unavailable", "Carrier rating service is temporarily unavailable."),
        ),
        expired_card_blocks(),
    ]
    for blocks in cases:
        assert "None" not in all_text(blocks)


def test_unknown_transit_renders_in_words():
    blocks = quote_card_blocks(
        _sample_parsed(), _load_shop(), token=TOKEN, show_all=True
    )
    text = all_text(blocks)
    assert "transit n/a" in text
    assert "0 days" not in text


def test_guaranteed_hint():
    blocks = quote_card_blocks(_sample_parsed(), _load_shop(), token=TOKEN)
    text = all_text(blocks)
    assert "Cheapest guaranteed:" in text
    assert "RL Carriers" in text


def test_header_and_section_length():
    shop = _load_shop()
    cases = [
        quote_card_blocks(_sample_parsed(), shop, token=TOKEN),
        quote_card_blocks(_sample_parsed(), shop, token=TOKEN, show_all=True),
    ]
    for blocks in cases:
        for block in blocks:
            if block.get("type") == "header":
                assert len(block["text"]["text"]) <= 150
            if block.get("type") == "section":
                assert len(block["text"]["text"]) < 3000


def test_error_card_shows_diagnostics():
    err = WarpError(
        "upstream_unavailable",
        "Carrier rating service is temporarily unavailable.",
        status=503,
        attempts=3,
        elapsed_ms=22400,
    )
    text = all_text(quote_error_blocks(_sample_parsed(), err))
    assert "after 3 attempts" in text
    assert "22.4s" in text
    assert "upstream_unavailable" in text
