"""Dispatch for Slack's interactive payloads.

One endpoint serves both commands: the quote card's own buttons and the shipment list's
expander all arrive here.
"""

from __future__ import annotations

import json
import logging

from app.commands import shipments
from app.deps import Runtime
from app.slack import blocks
from app.slack.payloads import BlockAction
from app.slack.respond import ephemeral, in_channel, post_response, replacing

logger = logging.getLogger(__name__)

EXPAND_SHIPMENT = "expand_shipment"
NEXT_PAGE = "shipments_next_page"
SHOW_ALL_RATES = "show_all_rates"
SHARE_QUOTE = "share_quote"

HANDLED = frozenset({EXPAND_SHIPMENT, NEXT_PAGE, SHOW_ALL_RATES, SHARE_QUOTE})


async def run(action: BlockAction, rt: Runtime) -> None:
    match action.action_id:
        case ac if ac == EXPAND_SHIPMENT:
            await _expand(action, rt)
        case ac if ac == NEXT_PAGE:
            await shipments.run(action.response_url, _page(action.value), rt)
        case ac if ac == SHOW_ALL_RATES:
            await _show_all(action, rt)
        case ac if ac == SHARE_QUOTE:
            await _share(action, rt)
        case _:
            logger.info("Ignoring unhandled action_id: %s", action.action_id)


async def _expand(action: BlockAction, rt: Runtime) -> None:
    try:
        payload = json.loads(action.value)
        shipment_id = str(payload["shipment_id"])
        order_id = str(payload["order_id"])
    except (ValueError, KeyError, TypeError):
        logger.warning("Malformed expand_shipment value")
        return
    await shipments.expand(action.response_url, shipment_id, order_id, rt)


async def _show_all(action: BlockAction, rt: Runtime) -> None:
    held = rt.cards.get(action.value)
    if held is None:
        await post_response(
            action.response_url,
            ephemeral(text="That quote has expired.", blocks=blocks.expired_card_blocks()),
            client=rt.http,
        )
        return
    card = blocks.quote_card_blocks(
        held.parsed,
        held.shop,
        token=action.value,
        show_all=True,
        cache_hit=held.cache_hit,
    )
    await post_response(
        action.response_url,
        replacing(ephemeral(text=f"Rates for {held.parsed.lane}", blocks=card)),
        client=rt.http,
    )


async def _share(action: BlockAction, rt: Runtime) -> None:
    held = rt.cards.get(action.value)
    if held is None:
        await post_response(
            action.response_url,
            ephemeral(text="That quote has expired.", blocks=blocks.expired_card_blocks()),
            client=rt.http,
        )
        return
    card = blocks.quote_card_blocks(
        held.parsed,
        held.shop,
        token=action.value,
        show_all=True,
        cache_hit=held.cache_hit,
    )
    card.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Shared by <@{action.user_id}>"}
            ],
        }
    )
    await post_response(
        action.response_url,
        in_channel(text=f"Rates for {held.parsed.lane}", blocks=card),
        client=rt.http,
    )


def _page(value: str) -> int:
    try:
        return max(1, int(value))
    except ValueError:
        return 1
