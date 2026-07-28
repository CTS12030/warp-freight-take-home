from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from app.models import (
    DocumentLink,
    Invoice,
    ParsedQuote,
    RateShop,
    ShipmentEvent,
    ShipmentsPage,
    TrackingResult,
    WarpBadRequest,
    WarpError,
    WarpNotFound,
    WarpUnavailable,
)
from app.warp.normalize import (
    normalize_documents,
    normalize_events,
    normalize_invoice,
    normalize_rate_shop,
    normalize_shipments_page,
    normalize_tracking,
)

_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


class WarpClient:
    """Read-only client for the Warp freight API.

    Every call goes through `_send`, which owns the retry policy. The upstream fails
    roughly one rate shop in seven with a 503 or 429, so retrying is not a nicety;
    without it the headline feature is broken one time in seven.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        max_attempts: int = 3,
        total_deadline_seconds: float = 45.0,
        client: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._total_deadline_seconds = total_deadline_seconds
        self._client = client
        self._sleep = sleep

    # ----------------------------------------------------------------- reads --

    async def freight_quote(self, parsed: ParsedQuote) -> RateShop:
        body = {
            "pickupDate": parsed.pickup_date.isoformat(),
            "pickupInfo": {"zipcode": parsed.lane.origin_zip},
            "deliveryInfo": {"zipcode": parsed.lane.dest_zip},
            "listItems": [
                {
                    "qty": parsed.pallets,
                    "packaging": "PALLET",
                    "weight": parsed.weight_lbs,
                    "weightUnit": "lbs",
                    "length": parsed.length_in,
                    "width": parsed.width_in,
                    "height": parsed.height_in,
                    "sizeUnit": "in",
                }
            ],
        }
        payload, attempts = await self._send(
            "POST", "/freights/freight-quote", json_body=body
        )
        return normalize_rate_shop(
            payload,
            quoted_at=datetime.now(timezone.utc),
            attempts=attempts,
        )

    async def track(self, tracking_numbers: list[str]) -> list[TrackingResult]:
        payload, _ = await self._send(
            "POST", "/freights/tracking", json_body={"trackingNumbers": tracking_numbers}
        )
        if not isinstance(payload, list):
            return []
        return [normalize_tracking(item) for item in payload if isinstance(item, dict)]

    async def events(self, shipment_id: str) -> list[ShipmentEvent]:
        payload, _ = await self._send("GET", f"/freights/events/{shipment_id}")
        return normalize_events(payload if isinstance(payload, dict) else {})

    async def shipments(self, page: int = 1, page_size: int = 5) -> ShipmentsPage:
        payload, _ = await self._send(
            "GET", "/freights/shipments", params={"page": page, "pageSize": page_size}
        )
        return normalize_shipments_page(payload if isinstance(payload, dict) else {})

    async def documents(self, order_id: str) -> list[DocumentLink]:
        payload, _ = await self._send("GET", f"/freights/documents/{order_id}")
        return normalize_documents(payload if isinstance(payload, dict) else {})

    async def invoice(self, order_id: str) -> Invoice:
        payload, _ = await self._send("GET", f"/freights/invoices/{order_id}")
        return normalize_invoice(payload if isinstance(payload, dict) else {})

    # -------------------------------------------------------------- transport --

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[Any, int]:
        """Perform one API call with retries. Returns the parsed body and the
        number of attempts it took."""
        start = time.monotonic()
        attempts = 0
        headers = {"apikey": self._api_key}
        url = f"{self._base_url}{path}"

        for attempt_index in range(self._max_attempts):
            attempts += 1
            try:
                response = await self._client.request(
                    method, url, json=json_body, params=params, headers=headers
                )
            except httpx.TransportError as exc:
                # A refused connection and a slow carrier are both retryable, but they
                # need different messages: one is our deployment, the other is theirs.
                if attempts >= self._max_attempts:
                    timed_out = isinstance(exc, httpx.TimeoutException)
                    raise self._unavailable(
                        "timeout" if timed_out else "connection_error",
                        (
                            "The freight service did not respond in time."
                            if timed_out
                            else "Could not reach the freight service."
                        ),
                        status=None,
                        attempts=attempts,
                        start=start,
                    )
                await self._maybe_sleep(
                    start=start,
                    attempts=attempts,
                    planned_sleep=self._backoff_seconds(attempt_index),
                )
                continue

            if response.is_success:
                return _decode(response), attempts

            status = response.status_code
            code, message = _error_from_response(response)

            if status in _RETRYABLE_STATUSES:
                if attempts >= self._max_attempts:
                    raise self._unavailable(
                        code, message, status=status, attempts=attempts, start=start
                    )
                retry_after = _parse_retry_after(response)
                await self._maybe_sleep(
                    start=start,
                    attempts=attempts,
                    planned_sleep=(
                        retry_after
                        if retry_after is not None
                        else self._backoff_seconds(attempt_index)
                    ),
                )
                continue

            raise _map_status(
                status, code, message, attempts=attempts, elapsed_ms=_elapsed_ms(start)
            )

        raise self._unavailable(
            "upstream_unavailable",
            "The freight service is unavailable.",
            status=503,
            attempts=attempts,
            start=start,
        )

    def _backoff_seconds(self, attempt_index: int) -> float:
        return (2**attempt_index) * random.uniform(0.8, 1.2)

    async def _maybe_sleep(
        self, *, start: float, attempts: int, planned_sleep: float
    ) -> None:
        elapsed = time.monotonic() - start
        if elapsed + planned_sleep > self._total_deadline_seconds:
            raise self._unavailable(
                "deadline_exceeded",
                "Gave up waiting for the freight service.",
                status=503,
                attempts=attempts,
                start=start,
            )
        await self._sleep(planned_sleep)

    def _unavailable(
        self,
        code: str,
        message: str,
        *,
        status: int | None,
        attempts: int,
        start: float,
    ) -> WarpUnavailable:
        return WarpUnavailable(
            code,
            message,
            status=status,
            attempts=attempts,
            elapsed_ms=_elapsed_ms(start),
        )


def _map_status(
    status: int, code: str, message: str, *, attempts: int, elapsed_ms: int
) -> WarpError:
    kind = {400: WarpBadRequest, 404: WarpNotFound}.get(status, WarpError)
    return kind(code, message, status=status, attempts=attempts, elapsed_ms=elapsed_ms)


def _decode(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _error_from_response(response: httpx.Response) -> tuple[str, str]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            code = payload.get("code")
            message = payload.get("message")
            if code is not None and message is not None:
                return str(code), str(message)
    except (ValueError, TypeError):
        pass
    return f"http_{response.status_code}", response.reason_phrase or "HTTP error"
