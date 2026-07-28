"""Short-lived store of rendered quote cards, keyed by an opaque token.

Slack buttons carry at most 2000 characters in their `value`, and a ten-carrier rate
shop does not fit. So the card keeps a token and the server keeps the card. The window
matches Slack's own: a `response_url` is valid for thirty minutes, so holding the card
for the same thirty minutes means a button either works or the message it belongs to is
already dead.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models import ParsedQuote, RateShop

TOKEN_TTL_SECONDS = 30 * 60
MAX_CARDS = 512


@dataclass(frozen=True)
class HeldQuote:
    parsed: ParsedQuote
    shop: RateShop
    cache_hit: bool


class CardStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = TOKEN_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict[str, tuple[float, HeldQuote]] = {}

    def put(self, held: HeldQuote) -> str:
        self._evict()
        if len(self._items) >= MAX_CARDS:
            oldest = min(self._items, key=lambda k: self._items[k][0])
            del self._items[oldest]
        token = uuid.uuid4().hex
        self._items[token] = (self._clock(), held)
        return token

    def get(self, token: str) -> HeldQuote | None:
        entry = self._items.get(token)
        if entry is None:
            return None
        stored_at, held = entry
        if self._clock() - stored_at > self._ttl:
            del self._items[token]
            return None
        return held

    def _evict(self) -> None:
        now = self._clock()
        for key in [k for k, (at, _) in self._items.items() if now - at > self._ttl]:
            del self._items[key]


def held_payload(held: HeldQuote) -> dict[str, Any]:
    return {"lane": str(held.parsed.lane), "options": len(held.shop.options)}
