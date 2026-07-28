from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models import (
    DocumentLink,
    Invoice,
    ShipmentDetail,
    ShipmentEvent,
    ShipmentSummary,
    ShipmentsPage,
    TrackingResult,
)
from app.slack.blocks import (
    format_status,
    shipment_detail_blocks,
    shipments_list_blocks,
    track_blocks,
    track_not_found_blocks,
)

UTC = timezone.utc


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


def _expand_buttons(blocks: list[dict]) -> list[dict]:
    buttons: list[dict] = []
    for block in blocks:
        if block.get("type") == "section":
            if accessory := block.get("accessory"):
                buttons.append(accessory)
        if block.get("type") == "actions":
            buttons.extend(block.get("elements", []))
    return buttons


def _action_ids(blocks: list[dict]) -> set[str]:
    return {b["action_id"] for b in _expand_buttons(blocks) if "action_id" in b}


def _sample_summary(**overrides) -> ShipmentSummary:
    defaults = dict(
        shipment_id="shp-1001",
        shipment_number="S-1001-IN",
        order_id="ord-1001",
        order_number="P-1001",
        status="in_transit",
        shipment_type="LTL",
        pickup="Los Angeles, CA 90021",
        delivery="Chicago, IL 60601",
        created=datetime(2026, 7, 23, tzinfo=UTC),
    )
    defaults.update(overrides)
    return ShipmentSummary(**defaults)


def test_format_status():
    assert format_status("in_transit") == "In transit"
    assert format_status("delivered") == "Delivered"
    assert format_status("canceled") == "Canceled"
    assert format_status(None) == "status unknown"


def test_in_transit_track_card():
    result = TrackingResult(
        tracking_number="S-1001-IN",
        found=True,
        status="in_transit",
        location="Amarillo, TX",
        order_id="P-1001",
        shipment_id="SH-1001",
        last_updated=datetime(2026, 7, 25, 14, 12, tzinfo=UTC),
    )
    blocks = track_blocks(result, [])
    text = all_text(blocks)
    assert "In transit" in text
    assert "Amarillo, TX" in text
    assert "S-1001-IN" in text


def test_canceled_shipment_no_location():
    result = TrackingResult(
        tracking_number="S-2000-IN",
        found=True,
        status="canceled",
        location=None,
    )
    blocks = track_blocks(result, [])
    text = all_text(blocks)
    assert "location not reported" in text
    assert "None" not in text


def test_timeline_most_recent_first_capped():
    events = [
        ShipmentEvent(
            message=f"event {i}",
            when=datetime(2026, 7, 20 + i, 10, 0, tzinfo=UTC),
            event_name="in_transit",
        )
        for i in range(7)
    ]
    result = TrackingResult(tracking_number="S-1001-IN", found=True, status="in_transit")
    blocks = track_blocks(result, events)
    timeline = next(
        b["text"]["text"]
        for b in blocks
        if b.get("type") == "section" and "`" in b["text"]["text"]
    )
    lines = [line for line in timeline.split("\n") if line.strip()]
    assert len(lines) == 5
    assert "event 6" in lines[0]


def test_not_found_card():
    blocks = track_not_found_blocks("BOGUS-999")
    text = all_text(blocks)
    assert "BOGUS-999" in text
    assert "None" not in text


def test_shipments_list():
    items = [_sample_summary(shipment_id=f"shp-{i}", shipment_number=f"S-{i}-IN") for i in range(1, 6)]
    page = ShipmentsPage(total=7, page=1, page_size=5, items=items)
    blocks = shipments_list_blocks(page)
    text = all_text(blocks)

    buttons = [b for b in _expand_buttons(blocks) if b.get("action_id") == "expand_shipment"]
    assert len(buttons) == 5
    for i, button in enumerate(buttons, start=1):
        payload = json.loads(button["value"])
        assert payload["shipment_id"] == f"shp-{i}"

    assert "Showing 1-5 of 7" in text
    next_buttons = [b for b in _expand_buttons(blocks) if b.get("action_id") == "shipments_next_page"]
    assert len(next_buttons) == 1
    assert next_buttons[0]["value"] == "2"


def test_shipments_last_page():
    items = [
        _sample_summary(shipment_id="shp-6", shipment_number="S-6-IN"),
        _sample_summary(shipment_id="shp-7", shipment_number="S-7-IN"),
    ]
    page = ShipmentsPage(total=7, page=2, page_size=5, items=items)
    blocks = shipments_list_blocks(page)
    text = all_text(blocks)
    assert "Showing 6-7 of 7" in text
    assert "shipments_next_page" not in _action_ids(blocks)


def test_shipments_empty_account():
    page = ShipmentsPage(total=0, page=1, page_size=5, items=[])
    blocks = shipments_list_blocks(page)
    assert blocks
    assert "no shipments" in all_text(blocks).lower()


def test_full_detail_card():
    events = [
        ShipmentEvent(
            message="departed Amarillo, TX",
            when=datetime(2026, 7, 25, 14, 12, tzinfo=UTC),
            event_name="in_transit",
        ),
        ShipmentEvent(
            message="picked up in Los Angeles, CA",
            when=datetime(2026, 7, 23, 8, 0, tzinfo=UTC),
            event_name="picked_up",
        ),
    ]
    detail = ShipmentDetail(
        summary=_sample_summary(),
        events=events,
        documents=[
            DocumentLink(
                doc_type="bol",
                url="http://localhost:3001/p/files/download/DOC-BOL-1002",
            ),
        ],
        invoice=Invoice(
            order_id="ord-1001",
            order_number="P-1001",
            status="paid",
            transit_cost=512.0,
            volume_discount=25.0,
            fuel_cost=61.44,
            grand_total=593.44,
            service_options=[("liftgate_delivery", 45.0)],
        ),
    )
    text = all_text(shipment_detail_blocks(detail))
    assert "$593.44" in text
    assert "http://localhost:3001/p/files/download/DOC-BOL-1002" in text
    assert "departed Amarillo, TX" in text


def test_detail_degrades_per_section():
    detail = ShipmentDetail(
        summary=_sample_summary(),
        events=None,
        events_note="No timeline on file.",
        documents=None,
        documents_note="No documents on file.",
        invoice=None,
        invoice_note="No invoice on file.",
    )
    blocks = shipment_detail_blocks(detail)
    text = all_text(blocks)
    assert "*Timeline*" in text
    assert "*Documents*" in text
    assert "*Invoice*" in text
    assert "No timeline on file." in text
    assert "No documents on file." in text
    assert "No invoice on file." in text
    assert "None" not in text


def test_detail_partial():
    events = [
        ShipmentEvent(
            message="in transit",
            when=datetime(2026, 7, 25, 14, 12, tzinfo=UTC),
            event_name="in_transit",
        ),
    ]
    detail = ShipmentDetail(
        summary=_sample_summary(),
        events=events,
        documents=None,
        documents_note="No documents on file.",
        invoice=None,
        invoice_note="No invoice on file.",
    )
    text = all_text(shipment_detail_blocks(detail))
    assert "in transit" in text.lower() or "In transit" in text
    assert "No documents on file." in text
    assert "No invoice on file." in text


def test_detail_notes_absent():
    detail = ShipmentDetail(
        summary=_sample_summary(),
        events=None,
        events_note=None,
        documents=None,
        documents_note=None,
        invoice=None,
        invoice_note=None,
    )
    blocks = shipment_detail_blocks(detail)
    text = all_text(blocks)
    assert "*Timeline*" in text
    assert "*Documents*" in text
    assert "*Invoice*" in text
    assert "Not available." in text
    assert "No documents on file." in text
    assert "None" not in text


def _all_cards() -> list[list[dict]]:
    result = TrackingResult(
        tracking_number="S-1001-IN",
        found=True,
        status="in_transit",
        location="Amarillo, TX",
        order_id="P-1001",
        shipment_id="SH-1001",
        last_updated=datetime(2026, 7, 25, 14, 12, tzinfo=UTC),
    )
    events = [
        ShipmentEvent(
            message="departed Amarillo, TX",
            when=datetime(2026, 7, 25, 14, 12, tzinfo=UTC),
            event_name="in_transit",
        ),
    ]
    items = [_sample_summary()]
    return [
        track_blocks(result, events),
        track_not_found_blocks("BOGUS-999"),
        shipments_list_blocks(ShipmentsPage(total=1, page=1, page_size=5, items=items)),
        shipments_list_blocks(ShipmentsPage(total=0, page=1, page_size=5, items=[])),
        shipment_detail_blocks(
            ShipmentDetail(
                summary=_sample_summary(),
                events=events,
                documents=[
                    DocumentLink(doc_type="bol", url="http://example.com/bol"),
                ],
                invoice=Invoice(
                    order_id="ord-1001",
                    order_number="P-1001",
                    status="paid",
                    transit_cost=512.0,
                    volume_discount=0.0,
                    fuel_cost=61.44,
                    grand_total=573.44,
                ),
            )
        ),
        shipment_detail_blocks(
            ShipmentDetail(
                summary=_sample_summary(),
                events=None,
                events_note=None,
                documents=None,
                documents_note=None,
                invoice=None,
                invoice_note=None,
            )
        ),
    ]


def test_block_legality():
    for blocks in _all_cards():
        for block in blocks:
            if block.get("type") == "header":
                assert len(block["text"]["text"]) <= 150
            if block.get("type") == "section":
                assert len(block["text"]["text"]) < 3000
