from __future__ import annotations

import re
from datetime import date, timedelta

from app.models import STANDARD_PALLET_IN, Lane, ParseError, ParsedQuote

USAGE_EXAMPLE = "/quote 90001 to 60601, 2 pallets, 1000 lbs"

HELP_WORDS = {"help", "-h", "--help", "?"}

WEIGHT_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(lb|lbs|pound|pounds|kg|kgs)\b",
    re.IGNORECASE,
)
PALLET_PATTERN = re.compile(
    r"(\d+)\s*(pallet|pallets|skid|skids)\b",
    re.IGNORECASE,
)
DIMENSION_PATTERN = re.compile(
    r"(\d+)\s*[x×]\s*(\d+)\s*[x×]\s*(\d+)(?:\s*(?:in|inches))?\b",
    re.IGNORECASE,
)
PICKUP_DATE_PATTERN = re.compile(
    r"(?:\b(?:pickup|on)\s+)?(\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
ZIP_PATTERN = re.compile(r"\b(\d{5})\b")

KG_TO_LBS = 2.20462


def next_business_day(today: date) -> date:
    candidate = today
    while True:
        candidate += timedelta(days=1)
        if candidate.weekday() < 5:
            return candidate


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _remove_match(text: str, match: re.Match[str]) -> str:
    return text[: match.start()] + text[match.end() :]


def parse_quote_command(text: str, *, today: date | None = None) -> ParsedQuote | ParseError:
    if today is None:
        today = date.today()

    if not text.strip() or text.strip().lower() in HELP_WORDS:
        return ParseError(
            kind="empty",
            message=f"Please provide a lane and weight. Example: {USAGE_EXAMPLE}",
        )

    remaining = text

    weight_lbs: int | None = None
    kg_source: int | None = None

    if weight_match := WEIGHT_PATTERN.search(remaining):
        value = _parse_number(weight_match.group(1))
        unit = weight_match.group(2).lower()
        if unit in {"kg", "kgs"}:
            kg_source = int(value) if value == int(value) else round(value)
            weight_lbs = round(value * KG_TO_LBS)
        else:
            weight_lbs = round(value)
        remaining = _remove_match(remaining, weight_match)

    pallets: int | None = None
    if pallet_match := PALLET_PATTERN.search(remaining):
        pallets = int(pallet_match.group(1))
        remaining = _remove_match(remaining, pallet_match)

    length_in: int | None = None
    width_in: int | None = None
    height_in: int | None = None
    if dim_match := DIMENSION_PATTERN.search(remaining):
        length_in = int(dim_match.group(1))
        width_in = int(dim_match.group(2))
        height_in = int(dim_match.group(3))
        remaining = _remove_match(remaining, dim_match)

    pickup_date: date | None = None
    if pickup_match := PICKUP_DATE_PATTERN.search(remaining):
        pickup_date = date.fromisoformat(pickup_match.group(1))
        remaining = _remove_match(remaining, pickup_match)

    zips = ZIP_PATTERN.findall(remaining)

    if len(zips) < 2:
        return ParseError(
            kind="invalid_input",
            message=(
                f"Two 5-digit ZIP codes (origin and destination) are required. "
                f"Example: {USAGE_EXAMPLE}"
            ),
        )

    if weight_lbs is None:
        return ParseError(
            kind="missing_weight",
            message=(
                f"Weight drives the price and must be provided — we will not guess it. "
                f"Example: {USAGE_EXAMPLE}"
            ),
        )

    if weight_lbs <= 0:
        return ParseError(
            kind="invalid_input",
            message=f"Weight must be greater than zero. Example: {USAGE_EXAMPLE}",
        )

    if pallets is not None and pallets <= 0:
        return ParseError(
            kind="invalid_input",
            message=f"Pallet count must be greater than zero. Example: {USAGE_EXAMPLE}",
        )

    assumptions: list[str] = []

    if pallets is None:
        pallets = 1
        assumptions.append("Assumed 1 pallet (none specified).")

    if length_in is None:
        length_in, width_in, height_in = STANDARD_PALLET_IN
        assumptions.append(f"Assumed a standard pallet ({length_in}x{width_in}x{height_in} in).")

    if pickup_date is None:
        pickup_date = next_business_day(today)
        assumptions.append(
            f"Assumed pickup on {pickup_date.isoformat()} (next business day)."
        )

    if kg_source is not None:
        assumptions.append(f"Converted {kg_source} kg to {weight_lbs} lbs.")

    return ParsedQuote(
        lane=Lane(origin_zip=zips[0], dest_zip=zips[1]),
        pallets=pallets,
        weight_lbs=weight_lbs,
        pickup_date=pickup_date,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        assumptions=assumptions,
    )
