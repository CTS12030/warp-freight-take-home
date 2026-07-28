"""The `/track` command."""

from __future__ import annotations

from typing import Any

from app.deps import Runtime
from app.models import ShipmentEvent, WarpError
from app.slack import blocks
from app.slack.payloads import SlashCommand
from app.slack.respond import ephemeral, post_response

USAGE = "/track S-1001-IN"


def ack(cmd: SlashCommand) -> tuple[dict[str, Any], str | None]:
    number = cmd.text.strip().split()[0] if cmd.text.strip() else ""
    if not number:
        return (
            ephemeral(text=f"Give me a tracking number, for example `{USAGE}`."),
            None,
        )
    # Tracking answers in well under a second, so this could be replied to inline. It
    # goes through the same acknowledge-then-deliver path anyway: one code path to
    # reason about, and no assumption that the real API is as quick as the mock.
    return ephemeral(text=f"Looking up {number}..."), number


async def run(cmd: SlashCommand, number: str, rt: Runtime) -> None:
    try:
        results = await rt.warp.track([number])
    except WarpError as err:
        await _deliver(
            cmd,
            rt,
            text=f"Could not look up {number}: {err.message}",
            card=blocks.quote_error_blocks(None, err),
        )
        return

    if not results or not results[0].found:
        await _deliver(
            cmd,
            rt,
            text=f"No shipment found for {number}.",
            card=blocks.track_not_found_blocks(number),
        )
        return

    result = results[0]
    events: list[ShipmentEvent] = []
    events_note: str | None = None
    if result.shipment_id:
        try:
            events = await rt.warp.events(result.shipment_id)
        except WarpError:
            # A shipment can exist with no timeline behind it. That is a row on the
            # card, not a failed command.
            events_note = "No timeline on file for this shipment."

    await _deliver(
        cmd,
        rt,
        text=f"{number}: {blocks.format_status(result.status)}",
        card=blocks.track_blocks(result, events, events_note=events_note),
    )


async def _deliver(
    cmd: SlashCommand, rt: Runtime, *, text: str, card: list[dict[str, Any]]
) -> None:
    await post_response(
        cmd.response_url, ephemeral(text=text, blocks=card), client=rt.http
    )
