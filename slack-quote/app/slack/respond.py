"""Delivery of delayed replies through Slack's `response_url`.

Slack drops a slash command that is not answered within three seconds, and the rate
shop takes four to sixteen. So the command handler acknowledges immediately and the
real answer arrives here, posted to the `response_url` that came with the request.

That URL is a bearer credential in itself, valid for thirty minutes and five uses, and
it needs no bot token — which is why this app holds no `xoxb-` secret at all.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 3


def ephemeral(*, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A reply only the person who ran the command can see."""
    payload: dict[str, Any] = {"response_type": "ephemeral", "text": text}
    if blocks is not None:
        payload["blocks"] = blocks
    return payload


def in_channel(*, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A reply everyone in the channel can see."""
    payload: dict[str, Any] = {"response_type": "in_channel", "text": text}
    if blocks is not None:
        payload["blocks"] = blocks
    return payload


def replacing(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "replace_original": True}


async def post_response(
    response_url: str,
    payload: dict[str, Any],
    *,
    client: httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bool:
    """Deliver one message. Returns whether Slack accepted it.

    This is the last step of a background task, so there is no caller left to handle an
    exception. A failure here is logged and swallowed; the alternative is an unhandled
    error in a fire-and-forget task and a user left staring at "working on it".
    """
    for attempt in range(MAX_DELIVERY_ATTEMPTS):
        try:
            response = await client.post(response_url, json=payload, timeout=10.0)
            if response.is_success:
                return True
            if response.status_code < 500:
                logger.error(
                    "Slack rejected a delayed reply: status=%s", response.status_code
                )
                return False
        except httpx.HTTPError as exc:
            logger.warning("Delivery to response_url failed: %s", type(exc).__name__)

        if attempt < MAX_DELIVERY_ATTEMPTS - 1:
            await sleep(2**attempt)

    logger.error("Gave up delivering a delayed reply after %d attempts", MAX_DELIVERY_ATTEMPTS)
    return False
