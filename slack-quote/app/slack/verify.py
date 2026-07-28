"""Slack request signature verification.

Implements the scheme documented at https://api.slack.com/authentication/verifying-requests-from-slack:
sign `v0:{timestamp}:{raw_body}` with the app's signing secret and compare against
the `X-Slack-Signature` header.

Two details that make this real rather than decorative:

- The digest is computed over the *raw* request bytes. Re-serialising a parsed form
  produces a different byte string and every signature would fail.
- Timestamps outside a five-minute window are rejected, so a captured request cannot
  be replayed later even though its signature stays valid forever.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

SIGNATURE_VERSION = "v0"
REPLAY_WINDOW_SECONDS = 60 * 5


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str = ""


def verify_slack_request(
    *,
    signing_secret: bytes,
    raw_body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    now: float | None = None,
) -> VerificationResult:
    if not signing_secret:
        return VerificationResult(False, "server is missing SLACK_SIGNING_SECRET")
    if not timestamp_header or not signature_header:
        return VerificationResult(False, "missing signature headers")

    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return VerificationResult(False, "malformed timestamp header")

    now = time.time() if now is None else now
    if abs(now - timestamp) > REPLAY_WINDOW_SECONDS:
        return VerificationResult(False, "timestamp outside replay window")

    basestring = b"%s:%d:%s" % (SIGNATURE_VERSION.encode(), timestamp, raw_body)
    digest = hmac.new(signing_secret, basestring, hashlib.sha256).hexdigest()
    expected = f"{SIGNATURE_VERSION}={digest}"

    if not hmac.compare_digest(expected, signature_header):
        return VerificationResult(False, "signature mismatch")

    return VerificationResult(True)


def sign(signing_secret: bytes, raw_body: bytes, timestamp: int) -> str:
    """Produce a valid signature. Used by the tests and by scripts/fake_slack.py."""
    basestring = b"%s:%d:%s" % (SIGNATURE_VERSION.encode(), timestamp, raw_body)
    digest = hmac.new(signing_secret, basestring, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"
