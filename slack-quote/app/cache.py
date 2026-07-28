"""In-process cache for rate shops, keyed by lane and freight.

A rate shop is a billable call to every carrier on the lane, and the upstream answers
429 when pushed. Two coordinators pricing the same lane a minute apart should cost one
call, not two. The TTL is ours to choose: `/freights/freight-quote` returns no expiry
field, so we hold quotes for a conservative window rather than pretending they are
fresh forever. A cache hit is always labelled as one in the Slack message.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.models import ParsedQuote, RateShop

MAX_ENTRIES = 256


def cache_key(parsed: ParsedQuote) -> str:
    return "|".join(
        str(part)
        for part in (
            parsed.lane.origin_zip,
            parsed.lane.dest_zip,
            parsed.pallets,
            parsed.weight_lbs,
            parsed.pickup_date.isoformat(),
            parsed.length_in,
            parsed.width_in,
            parsed.height_in,
        )
    )


class QuoteCache:
    def __init__(
        self,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, RateShop]] = {}

    def get(self, key: str) -> RateShop | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, shop = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[key]
            return None
        return shop

    def put(self, key: str, shop: RateShop) -> None:
        if self._ttl <= 0:
            return
        self._evict_expired()
        if len(self._entries) >= MAX_ENTRIES:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]
        self._entries[key] = (self._clock(), shop)

    def _evict_expired(self) -> None:
        now = self._clock()
        for key in [k for k, (at, _) in self._entries.items() if now - at > self._ttl]:
            del self._entries[key]
