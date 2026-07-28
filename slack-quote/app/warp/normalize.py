"""Normalize raw Warp freight-quote payloads into domain types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import (
    DocumentLink,
    Invoice,
    RateOption,
    RateShop,
    ShipmentEvent,
    ShipmentSummary,
    ShipmentsPage,
    TrackingResult,
)


def _parse_rate(raw: dict[str, Any]) -> float | None:
    if "rate" not in raw:
        return None
    value = raw["rate"]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_service_level(raw: dict[str, Any]) -> str | None:
    value = raw.get("serviceLevel")
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def _parse_transit_days(raw: dict[str, Any]) -> float | None:
    transit_time = raw.get("transitTime")
    # Upstream sends 0 when transit is unknown; do not treat as same-day.
    if transit_time is None or transit_time == 0:
        return None
    return float(transit_time) / 86400.0


def _parse_option(raw: dict[str, Any]) -> RateOption | None:
    rate = _parse_rate(raw)
    if rate is None:
        return None
    return RateOption(
        option_id=str(raw.get("id", "")),
        carrier_name=str(raw.get("carrierName", "")),
        carrier_code=str(raw.get("carrierCode", "")),
        source=str(raw.get("source", "")),
        rate=rate,
        service_level=_parse_service_level(raw),
        transit_days=_parse_transit_days(raw),
    )


def _sort_key(option: RateOption) -> tuple[float, bool, float, str]:
    return (
        option.rate,
        option.transit_days is None,
        option.transit_days if option.transit_days is not None else 0.0,
        option.option_id,
    )


def normalize_rate_shop(
    payload: dict[str, Any],
    *,
    quoted_at: datetime,
    attempts: int = 1,
) -> RateShop:
    request_id = payload.get("requestId")
    if request_id is None:
        request_id = payload.get("id")

    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        options: list[RateOption] = []
    else:
        options = []
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            option = _parse_option(raw)
            if option is not None:
                options.append(option)
        options.sort(key=_sort_key)

    return RateShop(
        request_id=request_id,
        options=options,
        quoted_at=quoted_at,
        attempts=attempts,
    )


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _format_city_state(location: Any) -> str | None:
    if location is None:
        return None
    if not isinstance(location, dict):
        return None
    city = location.get("city")
    state = location.get("state")
    if city is None or state is None:
        return None
    return f"{city}, {state}"


def _format_city_state_zip(location: Any) -> str:
    if not isinstance(location, dict):
        return ""
    city = str(location.get("city", ""))
    state = str(location.get("state", ""))
    zipcode = str(location.get("zipcode", ""))
    return f"{city}, {state} {zipcode}"


def normalize_tracking(raw: dict[str, Any]) -> TrackingResult:
    tracking_number = str(raw.get("trackingNumber", ""))
    if raw.get("error"):
        return TrackingResult(tracking_number=tracking_number, found=False)

    status_info = raw.get("statusInfo") or {}
    if not isinstance(status_info, dict):
        status_info = {}

    return TrackingResult(
        tracking_number=tracking_number,
        found=True,
        status=str(status_info.get("status", "")) or None,
        last_updated=_parse_dt(status_info.get("lastUpdated")),
        location=_format_city_state(raw.get("location")),
        shipment_id=str(raw.get("shipmentId", "")) or None,
        order_id=str(raw.get("orderId", "")) or None,
    )


def normalize_events(payload: dict[str, Any]) -> list[ShipmentEvent]:
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        return []

    events: list[ShipmentEvent] = []
    for raw in raw_data:
        if not isinstance(raw, dict):
            continue
        events.append(
            ShipmentEvent(
                message=str(raw.get("message", "")),
                when=_parse_dt(raw.get("when")),
                event_name=str(raw.get("eventName", "")),
            )
        )

    parsed = [e for e in events if e.when is not None]
    unparsed = [e for e in events if e.when is None]
    # Sort on the epoch value rather than the datetime: mixing aware and naive
    # timestamps in one timeline would otherwise raise while rendering.
    parsed.sort(key=lambda e: e.when.timestamp())  # type: ignore[union-attr]
    return parsed + unparsed


def _parse_shipment_summary(raw: dict[str, Any]) -> ShipmentSummary:
    tracking = raw.get("trackingNumber")
    return ShipmentSummary(
        shipment_id=str(raw.get("shipmentId", "")),
        shipment_number=str(raw.get("shipmentNumber", "")),
        order_id=str(raw.get("orderId", "")),
        order_number=str(raw.get("orderNumber", "")),
        status=str(raw.get("status", "")),
        shipment_type=str(raw.get("shipmentType", "")),
        pickup=_format_city_state_zip(raw.get("pickup")),
        delivery=_format_city_state_zip(raw.get("delivery")),
        created=_parse_dt(raw.get("createDate")),
        tracking_number=str(tracking) if tracking is not None else None,
    )


def normalize_shipments_page(payload: dict[str, Any]) -> ShipmentsPage:
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        raw_data = []

    items: list[ShipmentSummary] = []
    for raw in raw_data:
        if isinstance(raw, dict):
            items.append(_parse_shipment_summary(raw))

    page = payload.get("page")
    page_size = payload.get("pageSize")
    total = payload.get("total")

    return ShipmentsPage(
        total=int(total) if total is not None else 0,
        page=int(page) if page is not None else 1,
        page_size=int(page_size) if page_size is not None else len(items),
        items=items,
    )


def normalize_documents(payload: dict[str, Any]) -> list[DocumentLink]:
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        return []

    links: list[DocumentLink] = []
    for raw in raw_data:
        if not isinstance(raw, dict):
            continue
        url = raw.get("url")
        if not url:
            continue
        shipment_number = raw.get("shipmentNumber")
        links.append(
            DocumentLink(
                doc_type=str(raw.get("type", "")),
                url=str(url),
                shipment_number=str(shipment_number) if shipment_number is not None else None,
            )
        )
    return links


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_invoice(payload: dict[str, Any]) -> Invoice:
    raw_options = payload.get("serviceOptions")
    service_options: list[tuple[str, float]] = []
    if isinstance(raw_options, list):
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            service_options.append(
                (str(raw.get("name", "")), _parse_float(raw.get("amount")))
            )

    return Invoice(
        order_id=str(payload.get("orderId", "")),
        order_number=str(payload.get("orderNumber", "")),
        status=str(payload.get("status", "")),
        transit_cost=_parse_float(payload.get("transitCost")),
        volume_discount=_parse_float(payload.get("volumeDiscount")),
        fuel_cost=_parse_float(payload.get("fuelCost")),
        grand_total=_parse_float(payload.get("grandTotal")),
        service_options=service_options,
    )
