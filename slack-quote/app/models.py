"""Shared domain types.

Every module in this app speaks these types. The Warp API's own shapes stop at
`app/warp/normalize.py`; nothing downstream of that should ever see a raw payload,
a transit time in seconds, or a price with six decimal places.

Optional fields mean "upstream did not tell us", never "use a sensible default".
A missing service level renders as unspecified; an unknown transit time renders as
unknown. Inventing either would put a number in front of a customer that no carrier
ever quoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

ParseErrorKind = Literal["empty", "missing_weight", "invalid_input"]

STANDARD_PALLET_IN = (48, 40, 48)


@dataclass(frozen=True)
class Lane:
    origin_zip: str
    dest_zip: str

    def __str__(self) -> str:
        return f"{self.origin_zip} -> {self.dest_zip}"


@dataclass(frozen=True)
class ParsedQuote:
    """A `/quote` command that survived validation and is safe to price."""

    lane: Lane
    pallets: int
    weight_lbs: int
    pickup_date: date
    length_in: int = STANDARD_PALLET_IN[0]
    width_in: int = STANDARD_PALLET_IN[1]
    height_in: int = STANDARD_PALLET_IN[2]

    # Human-readable notes about values we supplied rather than the user, e.g.
    # "Assumed a standard pallet (48x40x48 in)". Rendered on the quote card so a
    # coordinator can see what the price is actually based on.
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParseError:
    kind: ParseErrorKind
    # Slack mrkdwn, shown to the user immediately in the slash command response.
    message: str


# --------------------------------------------------------------------------- #
# Rates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RateOption:
    option_id: str
    carrier_name: str
    carrier_code: str
    source: str
    rate: float  # raw upstream value; round only when rendering
    service_level: str | None  # None -> upstream omitted it
    transit_days: float | None  # None -> upstream sent 0 or omitted it


@dataclass(frozen=True)
class RateShop:
    request_id: str | None
    options: list[RateOption]  # sorted cheapest-first by `rate`
    quoted_at: datetime
    attempts: int = 1

    @property
    def cheapest(self) -> RateOption | None:
        return self.options[0] if self.options else None


# --------------------------------------------------------------------------- #
# Tracking, shipments, documents, invoices
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TrackingResult:
    tracking_number: str
    found: bool
    status: str | None = None
    last_updated: datetime | None = None
    location: str | None = None  # "Amarillo, TX"; None for canceled shipments
    shipment_id: str | None = None
    order_id: str | None = None


@dataclass(frozen=True)
class ShipmentEvent:
    message: str
    when: datetime | None
    event_name: str


@dataclass(frozen=True)
class ShipmentSummary:
    shipment_id: str
    shipment_number: str
    order_id: str
    order_number: str
    status: str
    shipment_type: str
    pickup: str  # "Los Angeles, CA 90021"
    delivery: str
    created: datetime | None
    tracking_number: str | None = None


@dataclass(frozen=True)
class ShipmentsPage:
    total: int
    page: int
    page_size: int
    items: list[ShipmentSummary]

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total


@dataclass(frozen=True)
class DocumentLink:
    doc_type: str  # "bol" | "pod"
    url: str
    shipment_number: str | None = None


@dataclass(frozen=True)
class Invoice:
    order_id: str
    order_number: str
    status: str
    transit_cost: float
    volume_discount: float
    fuel_cost: float
    grand_total: float
    service_options: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentDetail:
    """Result of expanding one shipment.

    Each section is independent: the mock has shipments with events but no invoice,
    and shipments with neither. A `None` section plus a note is a rendered row that
    says so, not a failed message.
    """

    summary: ShipmentSummary
    events: list[ShipmentEvent] | None = None
    events_note: str | None = None
    documents: list[DocumentLink] | None = None
    documents_note: str | None = None
    invoice: Invoice | None = None
    invoice_note: str | None = None


# --------------------------------------------------------------------------- #
# Upstream failures
# --------------------------------------------------------------------------- #


class WarpError(Exception):
    """Base for every non-success outcome from the freight API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        attempts: int = 1,
        elapsed_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms


class WarpUnavailable(WarpError):
    """Transient upstream failure (503/429/timeout) that survived the retry budget."""


class WarpNotFound(WarpError):
    """404 from the API: unknown order, unknown shipment, or no rates on the lane."""


class WarpBadRequest(WarpError):
    """400 from the API: our request was malformed or missing a required field."""


# --------------------------------------------------------------------------- #
# Usage logging
# --------------------------------------------------------------------------- #

QuoteOutcome = Literal[
    "ok",
    "no_rates",
    "invalid_input",
    "missing_weight",
    "upstream_error",
]


@dataclass(frozen=True)
class QuoteLogEntry:
    """One row per `/quote`, whether it succeeded or not.

    Failures are the point: a lane we were asked about and could not price is the
    most valuable thing in this table.
    """

    ts: datetime
    slack_user_id: str
    slack_user_name: str
    slack_channel_id: str
    slack_channel_name: str
    raw_text: str
    outcome: QuoteOutcome
    latency_ms: int
    origin_zip: str | None = None
    dest_zip: str | None = None
    pallets: int | None = None
    weight_lbs: int | None = None
    pickup_date: date | None = None
    option_count: int | None = None
    cheapest_rate: float | None = None
    cheapest_carrier: str | None = None
    request_id: str | None = None
    attempts: int = 0
    cache_hit: bool = False
    error_code: str | None = None
    response_json: Any = None
