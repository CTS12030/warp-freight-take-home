"""The `/quote` command.

This is where Slack's three-second deadline meets a rate shop that takes four to
sixteen seconds. The handler answers immediately with what it understood, and the rates
arrive later through the `response_url`. Nothing slow happens before the acknowledgement
returns — including validation failures, which are answered instantly because they never
need the API at all.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.cache import cache_key
from app.cards import HeldQuote
from app.deps import Runtime
from app.models import ParsedQuote, ParseError, QuoteLogEntry, QuoteOutcome, RateShop, WarpError
from app.parse import parse_quote_command
from app.slack import blocks
from app.slack.payloads import SlashCommand
from app.slack.respond import ephemeral, post_response
from app.store import log_quote

logger = logging.getLogger(__name__)


def ack(cmd: SlashCommand) -> tuple[dict[str, Any], ParsedQuote | None]:
    """Build the immediate reply. Returns the body plus the parsed command when there
    is background work to schedule."""
    parsed = parse_quote_command(cmd.text)

    if isinstance(parsed, ParseError):
        if parsed.kind == "empty":
            # Asking for help is not a failed quote; counting it as one would poison
            # the "lanes we could not price" signal.
            return ephemeral(text="How to use /quote", blocks=blocks.help_blocks()), None
        _log(
            cmd,
            outcome="missing_weight" if parsed.kind == "missing_weight" else "invalid_input",
            latency_ms=0,
            error_code=parsed.kind,
        )
        return (
            ephemeral(text=parsed.message, blocks=blocks.parse_error_blocks(parsed)),
            None,
        )

    return ephemeral(text=blocks.quote_ack_text(parsed)), parsed


async def run(cmd: SlashCommand, parsed: ParsedQuote, rt: Runtime) -> None:
    """The slow half, executed after the acknowledgement has already been sent."""
    started = time.perf_counter()

    key = cache_key(parsed)
    shop = rt.cache.get(key)
    cache_hit = shop is not None

    if shop is None:
        try:
            shop = await rt.warp.freight_quote(parsed)
        except WarpError as err:
            _log(
                cmd,
                outcome="upstream_error",
                latency_ms=_elapsed_ms(started),
                parsed=parsed,
                attempts=err.attempts,
                error_code=err.code,
            )
            await _deliver(
                cmd,
                rt,
                text=f"Could not price {parsed.lane}: {err.message}",
                card=blocks.quote_error_blocks(parsed, err),
            )
            return
        rt.cache.put(key, shop)

    if not shop.options:
        _log(
            cmd,
            outcome="no_rates",
            latency_ms=_elapsed_ms(started),
            parsed=parsed,
            shop=shop,
            cache_hit=cache_hit,
        )
        await _deliver(
            cmd,
            rt,
            text=f"No carrier returned a rate for {parsed.lane}.",
            card=blocks.no_rates_blocks(parsed),
        )
        return

    token = rt.cards.put(HeldQuote(parsed=parsed, shop=shop, cache_hit=cache_hit))
    _log(
        cmd,
        outcome="ok",
        latency_ms=_elapsed_ms(started),
        parsed=parsed,
        shop=shop,
        cache_hit=cache_hit,
    )
    await _deliver(
        cmd,
        rt,
        text=f"Rates for {parsed.lane}",
        card=blocks.quote_card_blocks(parsed, shop, token=token, cache_hit=cache_hit),
    )


async def _deliver(
    cmd: SlashCommand, rt: Runtime, *, text: str, card: list[dict[str, Any]]
) -> None:
    await post_response(
        cmd.response_url, ephemeral(text=text, blocks=card), client=rt.http
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _log(
    cmd: SlashCommand,
    *,
    outcome: QuoteOutcome,
    latency_ms: int,
    parsed: ParsedQuote | None = None,
    shop: RateShop | None = None,
    attempts: int = 0,
    cache_hit: bool = False,
    error_code: str | None = None,
) -> None:
    from app.config import settings

    cheapest = shop.cheapest if shop else None
    log_quote(
        QuoteLogEntry(
            ts=datetime.now(timezone.utc),
            slack_user_id=cmd.user_id,
            slack_user_name=cmd.user_name,
            slack_channel_id=cmd.channel_id,
            slack_channel_name=cmd.channel_name,
            raw_text=cmd.text,
            outcome=outcome,
            latency_ms=latency_ms,
            origin_zip=parsed.lane.origin_zip if parsed else None,
            dest_zip=parsed.lane.dest_zip if parsed else None,
            pallets=parsed.pallets if parsed else None,
            weight_lbs=parsed.weight_lbs if parsed else None,
            pickup_date=parsed.pickup_date if parsed else None,
            option_count=len(shop.options) if shop else None,
            cheapest_rate=cheapest.rate if cheapest else None,
            cheapest_carrier=cheapest.carrier_name if cheapest else None,
            request_id=shop.request_id if shop else None,
            attempts=shop.attempts if shop else attempts,
            cache_hit=cache_hit,
            error_code=error_code,
        ),
        path=settings.db_path,
    )
