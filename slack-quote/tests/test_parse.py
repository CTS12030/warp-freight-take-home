from __future__ import annotations

from datetime import date

import pytest

from app.models import ParseError, ParsedQuote
from app.parse import USAGE_EXAMPLE, next_business_day, parse_quote_command

TODAY = date(2026, 7, 28)


def test_full_quote():
    result = parse_quote_command("90001 to 60601, 2 pallets, 1000 lbs", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.lane.origin_zip == "90001"
    assert result.lane.dest_zip == "60601"
    assert result.pallets == 2
    assert result.weight_lbs == 1000
    assert result.length_in == 48
    assert result.width_in == 40
    assert result.height_in == 48
    assert not any("pallet" in a.lower() and "assumed" in a.lower() and "1 pallet" in a for a in result.assumptions)
    assert not any("2 pallet" in a for a in result.assumptions)


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_input(text: str):
    result = parse_quote_command(text, today=TODAY)
    assert isinstance(result, ParseError)
    assert result.kind == "empty"


def test_missing_weight():
    result = parse_quote_command("90001 to 60601, 2 pallets", today=TODAY)
    assert isinstance(result, ParseError)
    assert result.kind == "missing_weight"
    assert USAGE_EXAMPLE in result.message


def test_four_digit_origin_zip():
    result = parse_quote_command("9001 to 60601, 1000 lbs", today=TODAY)
    assert isinstance(result, ParseError)
    assert result.kind == "invalid_input"


def test_leading_zero_zip_is_valid():
    # Availability for 00501 is the API's call, not the parser's.
    result = parse_quote_command("00501 to 60601, 1 pallet, 500 lbs", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.lane.origin_zip == "00501"


def test_default_pallet_count():
    result = parse_quote_command("from 90001 to 60601 1000 lbs", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.pallets == 1
    assert any("Assumed 1 pallet" in a for a in result.assumptions)


def test_skids_and_comma_weight():
    result = parse_quote_command("90001 -> 60601, 3 skids, 2,500 lbs", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.pallets == 3
    assert result.weight_lbs == 2500


def test_kg_conversion():
    result = parse_quote_command("90001 to 60601, 1 pallet, 500 kg", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.weight_lbs == 1102
    assert any("Converted 500 kg to 1102 lbs" in a for a in result.assumptions)


def test_custom_dimensions():
    result = parse_quote_command("90001 to 60601, 2 pallets, 1000 lbs, 48x40x60", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.height_in == 60
    assert not any("standard pallet" in a for a in result.assumptions)


def test_explicit_pickup_date():
    result = parse_quote_command(
        "90001 to 60601, 1 pallet, 1000 lbs, pickup 2026-08-14",
        today=TODAY,
    )
    assert isinstance(result, ParsedQuote)
    assert result.pickup_date == date(2026, 8, 14)
    assert not any("next business day" in a for a in result.assumptions)


def test_five_digit_weight_not_confused_with_zip():
    result = parse_quote_command("90001 to 60601, 1 pallet, 10000 lbs", today=TODAY)
    assert isinstance(result, ParsedQuote)
    assert result.weight_lbs == 10000
    assert result.lane.origin_zip == "90001"
    assert result.lane.dest_zip == "60601"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 7, 29), date(2026, 7, 30)),
        (date(2026, 7, 31), date(2026, 8, 3)),
        (date(2026, 8, 1), date(2026, 8, 3)),
        (date(2026, 8, 2), date(2026, 8, 3)),
    ],
)
def test_next_business_day(today: date, expected: date):
    assert next_business_day(today) == expected


def test_zero_weight():
    result = parse_quote_command("90001 to 60601, 1 pallet, 0 lbs", today=TODAY)
    assert isinstance(result, ParseError)
    assert result.kind == "invalid_input"
