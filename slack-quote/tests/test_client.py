from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models import (
    Lane,
    ParsedQuote,
    RateShop,
    WarpBadRequest,
    WarpNotFound,
    WarpUnavailable,
)
from app.warp.client import WarpClient

FIXTURE = Path(__file__).resolve().parents[2] / "mock" / "fixtures" / "freight-quote.json"


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _load_success_body() -> dict:
    return json.loads(FIXTURE.read_text())


def _sample_quote() -> ParsedQuote:
    return ParsedQuote(
        lane=Lane(origin_zip="90021", dest_zip="10001"),
        pallets=1,
        weight_lbs=500,
        pickup_date=date(2026, 7, 28),
    )


def _queue_handler(responses: list[httpx.Response | Exception]):
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise RuntimeError("no more mocked responses")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


async def _build_client(
    handler,
    *,
    max_attempts: int = 3,
    total_deadline_seconds: float = 45.0,
) -> tuple[WarpClient, FakeSleep]:
    fake_sleep = FakeSleep()
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = WarpClient(
        base_url="http://test",
        api_key="secret-key",
        max_attempts=max_attempts,
        total_deadline_seconds=total_deadline_seconds,
        client=http_client,
        sleep=fake_sleep,
    )
    return client, fake_sleep


async def test_success_on_first_try():
    success = _load_success_body()
    client, fake_sleep = await _build_client(
        _queue_handler([httpx.Response(200, json=success)])
    )

    result = await client.freight_quote(_sample_quote())

    assert isinstance(result, RateShop)
    assert result.attempts == 1
    assert len(result.options) == 10
    assert result.cheapest is not None
    assert result.cheapest.option_id == "opt_fwra"
    assert fake_sleep.calls == []


async def test_retries_503_then_succeeds():
    success = _load_success_body()
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    503,
                    json={
                        "code": "upstream_unavailable",
                        "message": "Carrier rating service is temporarily unavailable.",
                    },
                    headers={"Retry-After": "2"},
                ),
                httpx.Response(200, json=success),
            ]
        )
    )

    result = await client.freight_quote(_sample_quote())

    assert result.attempts == 2
    assert fake_sleep.calls == [2.0]


async def test_honors_retry_after_on_429():
    success = _load_success_body()
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    429,
                    json={
                        "code": "rate_limit_exceeded",
                        "message": "Too many requests, slow down.",
                    },
                    headers={"Retry-After": "3"},
                ),
                httpx.Response(200, json=success),
            ]
        )
    )

    await client.freight_quote(_sample_quote())

    assert fake_sleep.calls == [3.0]


async def test_gives_up_after_max_attempts():
    error_body = {
        "code": "upstream_unavailable",
        "message": "Carrier rating service is temporarily unavailable.",
    }
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(503, json=error_body, headers={"Retry-After": "1"}),
                httpx.Response(503, json=error_body, headers={"Retry-After": "1"}),
                httpx.Response(503, json=error_body, headers={"Retry-After": "1"}),
            ]
        )
    )

    with pytest.raises(WarpUnavailable) as exc_info:
        await client.freight_quote(_sample_quote())

    err = exc_info.value
    assert err.attempts == 3
    assert err.code == "upstream_unavailable"
    assert err.status == 503
    assert len(fake_sleep.calls) == 2


async def test_400_is_not_retried():
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    400,
                    json={
                        "code": "required_field_missing",
                        "message": "pickupDate is required!",
                    },
                )
            ]
        )
    )

    with pytest.raises(WarpBadRequest):
        await client.freight_quote(_sample_quote())

    assert fake_sleep.calls == []


async def test_404_is_not_retried():
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    404,
                    json={"code": "not_found", "message": "Shipment not found."},
                )
            ]
        )
    )

    with pytest.raises(WarpNotFound):
        await client.freight_quote(_sample_quote())

    assert fake_sleep.calls == []


async def test_timeout_is_retried():
    success = _load_success_body()
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.ReadTimeout("boom"),
                httpx.Response(200, json=success),
            ]
        )
    )

    result = await client.freight_quote(_sample_quote())

    assert result.attempts == 2
    assert len(fake_sleep.calls) == 1


async def test_backoff_without_retry_after():
    success = _load_success_body()
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    503,
                    json={
                        "code": "upstream_unavailable",
                        "message": "Carrier rating service is temporarily unavailable.",
                    },
                ),
                httpx.Response(200, json=success),
            ]
        )
    )

    await client.freight_quote(_sample_quote())

    assert len(fake_sleep.calls) == 1
    assert 0.8 <= fake_sleep.calls[0] <= 1.2


async def test_deadline_stops_retry_loop():
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    503,
                    json={
                        "code": "upstream_unavailable",
                        "message": "Carrier rating service is temporarily unavailable.",
                    },
                    headers={"Retry-After": "2"},
                )
            ]
        ),
        total_deadline_seconds=0.0,
    )

    with pytest.raises(WarpUnavailable):
        await client.freight_quote(_sample_quote())

    assert fake_sleep.calls == []


async def test_empty_lane_is_success():
    client, fake_sleep = await _build_client(
        _queue_handler(
            [
                httpx.Response(
                    200,
                    json={"id": "x", "requestId": "x", "options": []},
                )
            ]
        )
    )

    result = await client.freight_quote(_sample_quote())

    assert result.options == []
    assert fake_sleep.calls == []
