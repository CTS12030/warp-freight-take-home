"""HTTP surface: two Slack endpoints and a health check.

Both Slack endpoints follow the same shape, and the order matters:

    verify the signature -> parse -> answer NOW -> do the slow work afterwards

FastAPI's `BackgroundTasks` run after the response has been sent, which is exactly the
contract Slack's three-second deadline needs. Nothing that can block goes above the
`return`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.commands import actions, quote, shipments, track
from app.config import settings
from app.deps import Runtime, build_runtime
from app.slack.payloads import parse_block_action, parse_slash_command
from app.slack.verify import verify_slack_request
from app.store import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    app.state.runtime = build_runtime(settings)
    if not settings.slack_signing_secret:
        logger.warning(
            "SLACK_SIGNING_SECRET is not set; every Slack request will be rejected"
        )
    try:
        yield
    finally:
        await app.state.runtime.http.aclose()


app = FastAPI(title="Slack Freight Desk", lifespan=lifespan)


def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


async def _verified_body(request: Request) -> bytes | Response:
    """Read the raw bytes and check Slack's signature over them.

    The digest must be taken over the body exactly as it arrived: parsing the form and
    re-encoding it would produce different bytes and fail every time.
    """
    raw = await request.body()
    result = verify_slack_request(
        signing_secret=settings.signing_secret_bytes,
        raw_body=raw,
        timestamp_header=request.headers.get("X-Slack-Request-Timestamp"),
        signature_header=request.headers.get("X-Slack-Signature"),
    )
    if not result.ok:
        logger.warning("Rejected an unverified request: %s", result.reason)
        return JSONResponse({"error": "invalid_request_signature"}, status_code=401)
    return raw


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "upstream": settings.warp_base_url}


@app.post("/slack/commands")
async def slack_commands(request: Request, background: BackgroundTasks) -> Any:
    raw = await _verified_body(request)
    if isinstance(raw, Response):
        return raw

    cmd = parse_slash_command(raw)
    rt = runtime(request)

    match cmd.command.lstrip("/"):
        case "quote":
            body, parsed = quote.ack(cmd)
            if parsed is not None:
                background.add_task(quote.run, cmd, parsed, rt)
            return body
        case "track":
            body, number = track.ack(cmd)
            if number is not None:
                background.add_task(track.run, cmd, number, rt)
            return body
        case "shipments":
            background.add_task(shipments.run, cmd.response_url, 1, rt)
            return shipments.ack(cmd)
        case unknown:
            logger.info("Unknown slash command: %s", unknown)
            return {"response_type": "ephemeral", "text": f"Unknown command {cmd.command}"}


@app.post("/slack/interactivity")
async def slack_interactivity(request: Request, background: BackgroundTasks) -> Response:
    raw = await _verified_body(request)
    if isinstance(raw, Response):
        return raw

    action = parse_block_action(raw)
    if action is not None and action.action_id in actions.HANDLED:
        background.add_task(actions.run, action, runtime(request))

    # Slack wants an empty 200 to dismiss the button's spinner; the real answer follows
    # on the response_url.
    return Response(status_code=200)
