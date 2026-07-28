#!/usr/bin/env python
"""Drive the app the way Slack does, without Slack.

Sends correctly signed slash commands and interaction payloads, and stands up a local
receiver that plays the part of `response_url` so the delayed reply can be printed. It
measures how long the acknowledgement took, which is the number Slack cares about: over
three seconds and the command is dropped.

    python scripts/fake_slack.py quote "90001 to 60601, 2 pallets, 1000 lbs"
    python scripts/fake_slack.py track S-1001-IN
    python scripts/fake_slack.py shipments
    python scripts/fake_slack.py action expand_shipment '{"shipment_id":"SH-1005","order_id":"O-1005"}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app.slack.verify import sign  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

APP_URL = os.getenv("APP_URL", "http://localhost:8000")
RECEIVER_PORT = int(os.getenv("FAKE_SLACK_PORT", "8099"))
SECRET = os.getenv("SLACK_SIGNING_SECRET", "").encode()

_received: list[dict] = []


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            _received.append(json.loads(body))
        except ValueError:
            _received.append({"raw": body.decode("utf-8", "replace")})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


def _start_receiver() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", RECEIVER_PORT), _Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post_signed(path: str, form: dict[str, str]) -> tuple[int, str, float]:
    body = urlencode(form).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": str(ts),
        "X-Slack-Signature": sign(SECRET, body, ts),
    }
    started = time.perf_counter()
    response = httpx.post(f"{APP_URL}{path}", content=body, headers=headers, timeout=30)
    return response.status_code, response.text, time.perf_counter() - started


def _render(payload: dict) -> str:
    lines: list[str] = []
    visibility = payload.get("response_type", "?")
    lines.append(f"[{visibility}] {payload.get('text', '')}")
    for block in payload.get("blocks") or []:
        kind = block.get("type")
        if kind == "header":
            lines.append(f"### {block['text']['text']}")
        elif kind == "section":
            lines.append(block.get("text", {}).get("text", ""))
            accessory = block.get("accessory")
            if accessory:
                lines.append(
                    f"      [{accessory['text']['text']} -> {accessory['action_id']}"
                    f" value={accessory.get('value')}]"
                )
        elif kind == "context":
            lines.append("  " + " | ".join(e["text"] for e in block["elements"]))
        elif kind == "actions":
            buttons = " ".join(
                f"[{e['text']['text']} -> {e['action_id']} value={e.get('value')}]"
                for e in block["elements"]
            )
            lines.append("  " + buttons)
        elif kind == "divider":
            lines.append("-" * 70)
    return "\n".join(lines)


def _wait_for_delivery(timeout: float, started: float, expect: int = 1) -> None:
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline and seen < expect:
        if len(_received) > seen:
            for payload in _received[seen:]:
                print(f"\n--- delayed reply after {time.time() - started:.1f}s ---")
                print(_render(payload))
            seen = len(_received)
        time.sleep(0.1)
    if seen == 0:
        print(f"\n!!! nothing delivered to response_url within {timeout:.0f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", choices=["quote", "track", "shipments", "action"])
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("value", nargs="?", default="")
    parser.add_argument("--wait", type=float, default=25.0)
    args = parser.parse_args(argv)

    if not SECRET:
        print("SLACK_SIGNING_SECRET is not set in slack-quote/.env", file=sys.stderr)
        return 1

    _start_receiver()
    response_url = f"http://127.0.0.1:{RECEIVER_PORT}/hook"

    if args.what == "action":
        payload = {
            "type": "block_actions",
            "user": {"id": "U123", "username": "jerry"},
            "channel": {"id": "C123", "name": "freight"},
            "response_url": response_url,
            "actions": [{"action_id": args.arg, "value": args.value}],
        }
        path = "/slack/interactivity"
        form = {"payload": json.dumps(payload)}
        label = f"action {args.arg}"
    else:
        path = "/slack/commands"
        form = {
            "command": f"/{args.what}",
            "text": args.arg,
            "user_id": "U123",
            "user_name": "jerry",
            "channel_id": "C123",
            "channel_name": "freight",
            "response_url": response_url,
        }
        label = f"/{args.what} {args.arg}".strip()

    started = time.time()
    status, text, ack_seconds = _post_signed(path, form)

    verdict = "OK" if ack_seconds < 3.0 else "TOO SLOW — Slack would have dropped this"
    print(f"$ {label}")
    print(f"ack: HTTP {status} in {ack_seconds * 1000:.0f}ms  [{verdict}]")
    if text.strip():
        try:
            print(_render(json.loads(text)))
        except ValueError:
            print(text)

    _wait_for_delivery(args.wait, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
