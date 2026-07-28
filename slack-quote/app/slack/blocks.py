from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import json

from app.models import ParseError, ParsedQuote, RateOption, RateShop, WarpError
from app.models import (
    DocumentLink,
    Invoice,
    ShipmentDetail,
    ShipmentEvent,
    ShipmentSummary,
    ShipmentsPage,
    TrackingResult,
)
from app.parse import USAGE_EXAMPLE


def format_money(amount: float) -> str:
    return f"${amount:,.2f}"


def format_transit(days: float | None) -> str:
    if days is None:
        return "transit n/a"
    if days == 1.0:
        return "1 day"
    text = f"{days:g}"
    suffix = "day" if days == 1 else "days"
    return f"{text} {suffix}"


def format_service_level(level: str | None) -> str:
    if level is None:
        return "service level unspecified"
    return level


def help_blocks() -> list[dict[str, Any]]:
    return [
        _section(
            f"Get freight rates for a lane. Weight is required.\n"
            f"Example: {USAGE_EXAMPLE}"
        ),
    ]


def parse_error_blocks(err: ParseError) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [_section(err.message)]
    if err.kind == "missing_weight":
        blocks.append(
            _context(
                "We do not guess weight because it directly changes the price."
            )
        )
    return blocks


def format_pallets(count: int) -> str:
    return f"{count} pallet" if count == 1 else f"{count} pallets"


def quote_ack_text(parsed: ParsedQuote) -> str:
    return (
        f"Rate-shopping {parsed.lane.origin_zip} -> {parsed.lane.dest_zip}"
        f" · {format_pallets(parsed.pallets)} · {parsed.weight_lbs:,} lbs"
        f" · pickup {parsed.pickup_date.isoformat()}"
        f" — this usually takes 5-15 seconds."
    )


def quote_card_blocks(
    parsed: ParsedQuote,
    shop: RateShop,
    *,
    token: str,
    show_all: bool = False,
    cache_hit: bool = False,
) -> list[dict[str, Any]]:
    total = len(shop.options)
    shown = shop.options if show_all else shop.options[:3]

    blocks: list[dict[str, Any]] = [
        _header(f"Rates: {parsed.lane.origin_zip} -> {parsed.lane.dest_zip}"),
        _context(_freight_summary(parsed)),
        _section(_rate_lines(shown)),
    ]

    if not show_all and total > 3:
        blocks.append(_context(f"Showing the 3 cheapest of {total}."))

    cheapest_guaranteed = _cheapest_guaranteed(shop.options)
    if cheapest_guaranteed is not None and cheapest_guaranteed not in shown:
        blocks.append(
            _context(
                f"Cheapest guaranteed: {format_money(cheapest_guaranteed.rate)}"
                f" · {cheapest_guaranteed.carrier_name}"
                f" · {format_transit(cheapest_guaranteed.transit_days)}."
            )
        )

    buttons: list[dict[str, Any]] = []
    if not show_all and total > 3:
        buttons.append(
            _button(f"Show all {total}", action_id="show_all_rates", value=token)
        )
    buttons.append(_button("Share to channel", action_id="share_quote", value=token))
    blocks.append({"type": "actions", "elements": buttons})

    if parsed.assumptions:
        blocks.append(_context(" ".join(parsed.assumptions)))

    blocks.append({"type": "divider"})
    blocks.append(_context(_footer(shop, total, cache_hit=cache_hit)))

    return blocks


def no_rates_blocks(parsed: ParsedQuote) -> list[dict[str, Any]]:
    return [
        _section(
            f"No carrier returned a rate for {parsed.lane.origin_zip} -> "
            f"{parsed.lane.dest_zip}."
        ),
        _context(
            f"{format_pallets(parsed.pallets)} · {parsed.weight_lbs:,} lbs"
            f" · pickup {parsed.pickup_date.isoformat()}"
        ),
        _context(
            "This lane came back empty — not a system error. "
            "Try a nearby ZIP or different pickup date."
        ),
    ]


def quote_error_blocks(
    parsed: ParsedQuote | None, err: WarpError
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [_section(err.message)]
    elapsed_s = err.elapsed_ms / 1000.0
    blocks.append(
        _context(
            f"{err.code} · after {err.attempts} attempts · over {elapsed_s:.1f}s"
        )
    )
    blocks.append(_context("Please try again shortly."))
    return blocks


def expired_card_blocks() -> list[dict[str, Any]]:
    return [
        _section("This quote has expired."),
        _context(f"Run the command again. Example: {USAGE_EXAMPLE}"),
    ]


def _freight_summary(parsed: ParsedQuote) -> str:
    return (
        f"{format_pallets(parsed.pallets)} · {parsed.weight_lbs:,} lbs"
        f" · {parsed.length_in}x{parsed.width_in}x{parsed.height_in} in"
        f" · pickup {parsed.pickup_date.isoformat()}"
    )


def _rate_lines(options: list[RateOption]) -> str:
    return "\n".join(
        f"`{i}`  *{format_money(o.rate)}*  ·  {o.carrier_name}"
        f"  ·  {format_transit(o.transit_days)}"
        f"  ·  {format_service_level(o.service_level)}"
        for i, o in enumerate(options, start=1)
    )


def _cheapest_guaranteed(options: list[RateOption]) -> RateOption | None:
    for option in options:
        if (
            option.service_level is not None
            and option.service_level.lower() == "guaranteed"
        ):
            return option
    return None


def _footer(shop: RateShop, total: int, *, cache_hit: bool) -> str:
    parts = [
        "Indicative rate, not a booking",
        f"{total} carriers",
        _format_quoted_at(shop.quoted_at),
    ]
    if shop.request_id is not None:
        parts.append(f"req {shop.request_id}")
    if cache_hit:
        parts.append("cached")
    return " · ".join(parts)


def _format_quoted_at(dt: datetime) -> str:
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("quoted %Y-%m-%d %H:%M UTC")


def _header(text: str) -> dict[str, Any]:
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": text, "emoji": True},
    }


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(*lines: str) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": line} for line in lines],
    }


def _button(text: str, *, action_id: str, value: str) -> dict[str, Any]:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "action_id": action_id,
        "value": value,
    }


def format_status(status: str | None) -> str:
    if not status:
        return "status unknown"
    text = status.replace("_", " ")
    return text[0].upper() + text[1:] if text else "status unknown"


def track_blocks(
    result: TrackingResult,
    events: list[ShipmentEvent],
    *,
    events_note: str | None = None,
) -> list[dict[str, Any]]:
    location = result.location if result.location else "location not reported"
    blocks: list[dict[str, Any]] = [
        _header(f"Shipment {result.tracking_number}"),
        _section(f"*{format_status(result.status)}* · {location}"),
        _context(_track_meta(result)),
    ]
    if events:
        blocks.append(_section(_event_lines(events)))
    if events_note is not None:
        blocks.append(_context(events_note))
    return blocks


def track_not_found_blocks(tracking_number: str) -> list[dict[str, Any]]:
    return [
        _section(
            f"No shipment record for *{tracking_number}*. "
            "Double-check the tracking number and try again."
        ),
    ]


def shipments_list_blocks(page: ShipmentsPage) -> list[dict[str, Any]]:
    if not page.items:
        return [
            _section("No shipments on this account yet."),
        ]

    blocks: list[dict[str, Any]] = [_header("Recent shipments")]
    for item in page.items:
        blocks.append(_shipment_row(item))

    start = (page.page - 1) * page.page_size + 1
    end = start + len(page.items) - 1
    blocks.append(_context(f"Showing {start}-{end} of {page.total}"))

    if page.has_next:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    _button(
                        "Next page",
                        action_id="shipments_next_page",
                        value=str(page.page + 1),
                    )
                ],
            }
        )
    return blocks


def shipment_detail_blocks(detail: ShipmentDetail) -> list[dict[str, Any]]:
    summary = detail.summary
    blocks: list[dict[str, Any]] = [
        _header(summary.shipment_number),
        _context(
            f"{summary.pickup} -> {summary.delivery}"
            f" · {format_status(summary.status)}"
            f" · Order {summary.order_number}"
        ),
        _section(_detail_timeline(detail)),
        _section(_detail_documents(detail)),
        _section(_detail_invoice(detail)),
    ]
    return blocks


def _track_meta(result: TrackingResult) -> str:
    parts: list[str] = []
    if result.order_id is not None:
        parts.append(f"Order {result.order_id}")
    if result.shipment_id is not None:
        parts.append(f"Shipment {result.shipment_id}")
    if result.last_updated is not None:
        parts.append(_format_updated_at(result.last_updated))
    return " · ".join(parts)


def _format_updated_at(dt: datetime) -> str:
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("updated %Y-%m-%d %H:%M UTC")


def _format_event_when(dt: datetime | None) -> str:
    if dt is None:
        return "--------------"
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%d %H:%M")


def _event_lines(events: list[ShipmentEvent], *, max_events: int = 5) -> str:
    # The upstream `message` already reads as prose ("In transit — departed Amarillo,
    # TX"); prefixing the machine event name only repeats it back to the reader.
    recent = list(reversed(events))[:max_events]
    return "\n".join(
        f"`{_format_event_when(e.when)}`  {e.message}" for e in recent
    )


def _shipment_row(item: ShipmentSummary) -> dict[str, Any]:
    line1 = f"*{item.shipment_number}* · {format_status(item.status)}"
    line2_parts = [
        f"{item.pickup} -> {item.delivery}",
        item.shipment_type,
    ]
    if item.created is not None:
        line2_parts.append(_format_created_date(item.created))
    text = f"{line1}\n{' · '.join(line2_parts)}"
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
        "accessory": _button(
            "Details",
            action_id="expand_shipment",
            value=json.dumps(
                {"shipment_id": item.shipment_id, "order_id": item.order_id}
            ),
        ),
    }


def _format_created_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%d")


def _detail_timeline(detail: ShipmentDetail) -> str:
    if detail.events:
        return f"*Timeline*\n{_event_lines(detail.events)}"
    note = detail.events_note if detail.events_note is not None else "Not available."
    return f"*Timeline*\n{note}"


def _detail_documents(detail: ShipmentDetail) -> str:
    if detail.documents:
        links = " · ".join(
            f"<{doc.url}|{doc.doc_type.upper()}>" for doc in detail.documents
        )
        return f"*Documents*\n{links}"
    note = detail.documents_note if detail.documents_note is not None else "No documents on file."
    return f"*Documents*\n{note}"


def _detail_invoice(detail: ShipmentDetail) -> str:
    if detail.invoice is not None:
        return f"*Invoice*\n{_invoice_body(detail.invoice)}"
    note = detail.invoice_note if detail.invoice_note is not None else "Not available."
    return f"*Invoice*\n{note}"


def _invoice_body(invoice: Invoice) -> str:
    lines = [f"Total *{format_money(invoice.grand_total)}*"]
    breakdown = _invoice_breakdown(invoice)
    if breakdown:
        lines.append(breakdown)
    lines.append(format_status(invoice.status))
    return "\n".join(lines)


def _invoice_breakdown(invoice: Invoice) -> str:
    parts = [
        f"transit {format_money(invoice.transit_cost)}",
        f"fuel {format_money(invoice.fuel_cost)}",
    ]
    if invoice.volume_discount:
        parts.append(f"discount -{format_money(invoice.volume_discount)}")
    for name, amount in invoice.service_options:
        parts.append(f"{name} {format_money(amount)}")
    return " · ".join(parts)
