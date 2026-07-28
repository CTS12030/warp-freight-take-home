from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.warp.normalize import (
    normalize_documents,
    normalize_events,
    normalize_invoice,
    normalize_shipments_page,
    normalize_tracking,
)

FIXTURES = Path(__file__).resolve().parents[2] / "mock" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_tracking_happy_path():
    tracking = _load("tracking.json")
    result = normalize_tracking(tracking["S-1001-IN"])
    assert result.found is True
    assert result.status == "in_transit"
    assert result.location == "Amarillo, TX"
    assert result.shipment_id == "SH-1001"
    assert result.order_id == "O-1001"
    assert isinstance(result.last_updated, datetime)
    assert result.last_updated.year == 2026
    assert result.last_updated.month == 7
    assert result.last_updated.day == 25


def test_tracking_canceled_no_location():
    tracking = _load("tracking.json")
    result = normalize_tracking(tracking["S-1003-CAN"])
    assert result.found is True
    assert result.status == "canceled"
    assert result.location is None


def test_tracking_unknown_number():
    result = normalize_tracking({"trackingNumber": "NOPE", "error": "not_found"})
    assert result.found is False
    assert result.status is None
    assert result.location is None
    assert result.tracking_number == "NOPE"


def test_events_chronological():
    events = _load("events.json")
    result = normalize_events(events["SH-1001"])
    assert len(result) == 4
    messages = [e.message for e in result]
    assert messages[0] == "Order received"
    assert messages[-1].startswith("In transit")
    whens = [e.when for e in result if e.when is not None]
    assert whens == sorted(whens)


def test_events_empty_input():
    assert normalize_events({}) == []


def test_shipments_page():
    shipments = _load("shipments.json")
    payload = {
        "total": 7,
        "page": 1,
        "pageSize": 5,
        "data": shipments["data"][:5],
    }
    page = normalize_shipments_page(payload)
    assert len(page.items) == 5
    assert page.total == 7
    assert page.has_next is True
    assert page.items[0].pickup == "Los Angeles, CA 90021"
    assert page.items[0].delivery == "Chicago, IL 60601"


def test_shipments_last_page():
    shipments = _load("shipments.json")
    payload = {
        "total": 7,
        "page": 2,
        "pageSize": 5,
        "data": shipments["data"][5:],
    }
    page = normalize_shipments_page(payload)
    assert page.has_next is False
    assert len(page.items) == 2


def test_documents():
    raw = (FIXTURES / "documents.json").read_text().replace(
        "__BASE__", "http://localhost:3001"
    )
    documents = json.loads(raw)
    links = normalize_documents(documents["O-1002"])
    assert len(links) == 2
    assert {d.doc_type for d in links} == {"bol", "pod"}
    assert all(d.url.startswith("http://localhost:3001/p/files/download/") for d in links)


def test_invoice_with_service_option():
    invoices = _load("invoices.json")
    invoice = normalize_invoice(invoices["O-1002"])
    assert invoice.grand_total == 593.44
    assert invoice.volume_discount == 25.0
    assert invoice.service_options == [("liftgate_delivery", 45.0)]


def test_invoice_no_service_options():
    invoices = _load("invoices.json")
    invoice = normalize_invoice(invoices["O-1001"])
    assert invoice.service_options == []
    assert invoice.grand_total == 739.6775
