"""The `/shipments` command and the expansion of one shipment."""

from __future__ import annotations

import asyncio
from typing import Any

from app.deps import Runtime
from app.models import Invoice, ShipmentDetail, ShipmentSummary, WarpError
from app.slack import blocks
from app.slack.payloads import SlashCommand
from app.slack.respond import ephemeral, post_response

PAGE_SIZE = 5
LOOKUP_PAGE_SIZE = 50


def ack(cmd: SlashCommand) -> dict[str, Any]:
    return ephemeral(text="Pulling recent shipments...")


async def run(response_url: str, page: int, rt: Runtime) -> None:
    try:
        result = await rt.warp.shipments(page=page, page_size=PAGE_SIZE)
    except WarpError as err:
        await _post(
            response_url,
            rt,
            text=f"Could not list shipments: {err.message}",
            card=blocks.quote_error_blocks(None, err),
        )
        return

    await _post(
        response_url,
        rt,
        text=f"Recent shipments (page {result.page})",
        card=blocks.shipments_list_blocks(result),
    )


async def expand(response_url: str, shipment_id: str, order_id: str, rt: Runtime) -> None:
    summary = await _find_summary(shipment_id, rt)
    if summary is None:
        await _post(
            response_url,
            rt,
            text=f"Shipment {shipment_id} is no longer on the account.",
            card=blocks.track_not_found_blocks(shipment_id),
        )
        return

    # Three independent sub-resources. On this account four of the seven shipments have
    # no invoice and no documents, and three have no timeline, so a single failure must
    # not blank the whole card: each section reports for itself.
    events, documents, invoice = await asyncio.gather(
        rt.warp.events(shipment_id),
        rt.warp.documents(order_id),
        rt.warp.invoice(order_id),
        return_exceptions=True,
    )

    detail = ShipmentDetail(
        summary=summary,
        events=_value(events, list),
        events_note=_note(events, "No timeline on file."),
        documents=_value(documents, list),
        documents_note=_note(documents, "No documents on file."),
        invoice=_value(invoice, Invoice),
        invoice_note=_note(invoice, "No invoice on file."),
    )
    await _post(
        response_url,
        rt,
        text=f"{summary.shipment_number} details",
        card=blocks.shipment_detail_blocks(detail),
    )


async def _find_summary(shipment_id: str, rt: Runtime) -> ShipmentSummary | None:
    try:
        page = await rt.warp.shipments(page=1, page_size=LOOKUP_PAGE_SIZE)
    except WarpError:
        return None
    return next((s for s in page.items if s.shipment_id == shipment_id), None)


def _value(result: Any, expected: type) -> Any:
    if isinstance(result, BaseException):
        return None
    if expected is list:
        return result if result else None
    return result


def _note(result: Any, missing: str) -> str | None:
    if isinstance(result, WarpError):
        return missing
    if isinstance(result, BaseException):
        return "Could not load this section."
    if isinstance(result, list) and not result:
        return missing
    return None


async def _post(
    response_url: str, rt: Runtime, *, text: str, card: list[dict[str, Any]]
) -> None:
    await post_response(response_url, ephemeral(text=text, blocks=card), client=rt.http)
