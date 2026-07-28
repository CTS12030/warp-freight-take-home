"""Process-wide runtime objects, built once at startup."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.cache import QuoteCache
from app.cards import CardStore
from app.config import Settings
from app.warp.client import WarpClient


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    http: httpx.AsyncClient
    warp: WarpClient
    cache: QuoteCache
    cards: CardStore


def build_runtime(settings: Settings) -> Runtime:
    # The quote endpoint can legitimately take sixteen seconds, so the read timeout has
    # to clear that comfortably or we would retry work that was about to succeed.
    http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    return Runtime(
        settings=settings,
        http=http,
        warp=WarpClient(
            base_url=settings.warp_base_url,
            api_key=settings.warp_api_key,
            max_attempts=settings.max_attempts,
            total_deadline_seconds=settings.total_deadline_seconds,
            client=http,
        ),
        cache=QuoteCache(settings.quote_cache_ttl_seconds),
        cards=CardStore(),
    )
