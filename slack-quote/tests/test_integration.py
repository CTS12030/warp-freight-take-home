"""End-to-end tests through the real FastAPI app.

These drive the same code path Slack does: a signed form post to `/slack/commands`,
an immediate acknowledgement, then a background task that delivers the real answer to
`response_url`. Both the freight API and Slack's receiving end are stubbed with one
`MockTransport`, so the whole loop runs in-process with no network and no waiting.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import QuoteCache
from app.cards import CardStore
from app.config import Settings
from app.deps import Runtime
from app.slack.verify import sign
from app.warp.client import WarpClient

FIXTURE = Path(__file__).resolve().parents[2] / "mock" / "fixtures" / "freight-quote.json"
SECRET = b"integration-test-secret"
HOOK = "https://hooks.slack.test/response"
UPSTREAM = "http://freight.test"


class Upstream:
    """A stand-in for both the freight API and Slack's response_url endpoint."""

    def __init__(self) -> None:
        self.deliveries: list[dict[str, Any]] = []
        self.quote_status = 200
        self.quote_body: dict[str, Any] = json.loads(FIXTURE.read_text())
        self.quote_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(HOOK):
            self.deliveries.append(json.loads(request.content))
            return httpx.Response(200, text="ok")
        if "/freights/freight-quote" in url:
            self.quote_calls += 1
            if self.quote_status != 200:
                return httpx.Response(
                    self.quote_status,
                    json={"code": "upstream_unavailable", "message": "Try again."},
                    headers={"Retry-After": "0"},
                )
            return httpx.Response(200, json=self.quote_body)
        return httpx.Response(404, json={"code": "not_found", "message": "no"})


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def client(upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        slack_signing_secret=SECRET.decode(),
        warp_base_url=UPSTREAM,
        warp_api_key="test-key",
        quote_cache_ttl_seconds=900,
        max_attempts=3,
        total_deadline_seconds=45.0,
        db_path=tmp_path / "quotes.db",
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    def build(_settings: Settings) -> Runtime:
        http = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle))
        return Runtime(
            settings=settings,
            http=http,
            warp=WarpClient(
                base_url=UPSTREAM,
                api_key="test-key",
                client=http,
                sleep=no_sleep,
            ),
            cache=QuoteCache(settings.quote_cache_ttl_seconds),
            cards=CardStore(),
        )

    from app import main as main_module

    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setattr("app.config.settings", settings)
    monkeypatch.setattr("app.main.build_runtime", build)

    with TestClient(main_module.app) as test_client:
        test_client.db_path = settings.db_path  # type: ignore[attr-defined]
        yield test_client


def post_command(client: TestClient, command: str, text: str) -> httpx.Response:
    body = urlencode(
        {
            "command": command,
            "text": text,
            "user_id": "U1",
            "user_name": "jerry",
            "channel_id": "C1",
            "channel_name": "freight",
            "response_url": HOOK,
        }
    ).encode()
    return _signed_post(client, "/slack/commands", body)


def post_action(client: TestClient, action_id: str, value: str) -> httpx.Response:
    payload = {
        "type": "block_actions",
        "user": {"id": "U1", "username": "jerry"},
        "channel": {"id": "C1", "name": "freight"},
        "response_url": HOOK,
        "actions": [{"action_id": action_id, "value": value}],
    }
    body = urlencode({"payload": json.dumps(payload)}).encode()
    return _signed_post(client, "/slack/interactivity", body)


def _signed_post(client: TestClient, path: str, body: bytes) -> httpx.Response:
    ts = int(time.time())
    return client.post(
        path,
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": sign(SECRET, body, ts),
        },
    )


def all_text(payload: dict[str, Any]) -> str:
    parts: list[str] = [payload.get("text", "")]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            parts.append(node)

    walk(payload.get("blocks"))
    return " ".join(parts)


def find_token(payload: dict[str, Any], action_id: str) -> str:
    for block in payload.get("blocks", []):
        for element in block.get("elements", []) if block.get("type") == "actions" else []:
            if element.get("action_id") == action_id:
                return str(element["value"])
    raise AssertionError(f"no {action_id} button in the card")


def rows(db_path: Path) -> list[dict[str, Any]]:
    import sqlite3

    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM quotes ORDER BY id")]
    finally:
        conn.close()


# --------------------------------------------------------------------- security --


def test_unsigned_request_is_rejected(client: TestClient) -> None:
    response = client.post("/slack/commands", content=b"command=/quote&text=hi")
    assert response.status_code == 401


def test_tampered_body_is_rejected(client: TestClient) -> None:
    ts = int(time.time())
    signed_for = b"command=/quote&text=original"
    response = client.post(
        "/slack/commands",
        content=b"command=/quote&text=TAMPERED",
        headers={
            "X-Slack-Request-Timestamp": str(ts),
            "X-Slack-Signature": sign(SECRET, signed_for, ts),
        },
    )
    assert response.status_code == 401


# ------------------------------------------------------------------------ quote --


def test_quote_acks_immediately_then_delivers(client: TestClient, upstream: Upstream) -> None:
    response = post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")

    assert response.status_code == 200
    ack = response.json()
    assert ack["response_type"] == "ephemeral"
    assert "Rate-shopping 90001 -> 60601" in ack["text"]
    # The acknowledgement must carry no rates: at this point none have been fetched.
    assert "432" not in json.dumps(ack)

    assert len(upstream.deliveries) == 1
    card = all_text(upstream.deliveries[0])
    assert "$432.29" in card
    assert "Forward Air" in card
    assert "Indicative rate, not a booking" in card


def test_quote_logs_a_row(client: TestClient) -> None:
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")
    logged = rows(client.db_path)  # type: ignore[attr-defined]
    assert len(logged) == 1
    assert logged[0]["outcome"] == "ok"
    assert logged[0]["origin_zip"] == "90001"
    assert logged[0]["option_count"] == 10
    assert logged[0]["cheapest_carrier"] == "Forward Air"


def test_missing_weight_never_calls_the_api(client: TestClient, upstream: Upstream) -> None:
    response = post_command(client, "/quote", "90001 to 60601, 2 pallets")

    assert "will not guess it" in response.json()["text"]
    assert upstream.quote_calls == 0
    assert upstream.deliveries == []
    assert rows(client.db_path)[0]["outcome"] == "missing_weight"  # type: ignore[attr-defined]


def test_help_is_not_logged_as_a_failed_quote(client: TestClient) -> None:
    post_command(client, "/quote", "")
    assert rows(client.db_path) == []  # type: ignore[attr-defined]


def test_empty_lane_is_an_answer_not_an_error(client: TestClient, upstream: Upstream) -> None:
    upstream.quote_body = {"id": "x", "requestId": "x", "options": []}
    post_command(client, "/quote", "00501 to 60601, 1 pallet, 500 lbs")

    card = all_text(upstream.deliveries[0])
    assert "No carrier returned a rate" in card
    assert rows(client.db_path)[0]["outcome"] == "no_rates"  # type: ignore[attr-defined]


def test_exhausted_retries_deliver_a_diagnostic_card(
    client: TestClient, upstream: Upstream
) -> None:
    upstream.quote_status = 503
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")

    assert upstream.quote_calls == 3
    card = all_text(upstream.deliveries[0])
    assert "after 3 attempts" in card
    assert "upstream_unavailable" in card
    assert "test-key" not in card

    logged = rows(client.db_path)[0]  # type: ignore[attr-defined]
    assert logged["outcome"] == "upstream_error"
    assert logged["attempts"] == 3


def test_second_identical_quote_is_served_from_cache(
    client: TestClient, upstream: Upstream
) -> None:
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")

    assert upstream.quote_calls == 1
    assert "cached" in all_text(upstream.deliveries[1])
    assert rows(client.db_path)[1]["cache_hit"] == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------- buttons --


def test_show_all_replaces_the_card_with_every_rate(
    client: TestClient, upstream: Upstream
) -> None:
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")
    token = find_token(upstream.deliveries[0], "show_all_rates")

    response = post_action(client, "show_all_rates", token)
    assert response.status_code == 200

    expanded = upstream.deliveries[1]
    assert expanded["replace_original"] is True
    assert "$760.57" in all_text(expanded)


def test_share_posts_to_the_channel(client: TestClient, upstream: Upstream) -> None:
    post_command(client, "/quote", "90001 to 60601, 2 pallets, 1000 lbs")
    token = find_token(upstream.deliveries[0], "share_quote")

    post_action(client, "share_quote", token)

    shared = upstream.deliveries[1]
    assert shared["response_type"] == "in_channel"
    assert "replace_original" not in shared
    assert "Shared by <@U1>" in all_text(shared)


def test_a_stale_token_says_so_instead_of_failing(
    client: TestClient, upstream: Upstream
) -> None:
    response = post_action(client, "show_all_rates", "0" * 32)

    assert response.status_code == 200
    assert "expired" in all_text(upstream.deliveries[0]).lower()
