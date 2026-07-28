"""Tests for Slack request signature verification."""

from __future__ import annotations

from app.slack.verify import REPLAY_WINDOW_SECONDS, sign, verify_slack_request

_SECRET = b"test-signing-secret"
_OTHER_SECRET = b"other-secret"
_NOW = 1_700_000_000.0
_BODY = b"token=giraffe&command=%2Fquote&text=90210+10001"


def _verify(**overrides: object):
    ts = int(_NOW)
    defaults = {
        "signing_secret": _SECRET,
        "raw_body": _BODY,
        "timestamp_header": str(ts),
        "signature_header": sign(_SECRET, _BODY, ts),
        "now": _NOW,
    }
    defaults.update(overrides)
    return verify_slack_request(**defaults)  # type: ignore[arg-type]


def test_correctly_signed_request_passes() -> None:
    result = _verify()
    assert result.ok is True
    assert result.reason == ""


def test_tampered_body_fails() -> None:
    ts = int(_NOW)
    result = _verify(
        raw_body=b"tampered=body",
        signature_header=sign(_SECRET, _BODY, ts),
    )
    assert result.ok is False
    assert "signature mismatch" in result.reason


def test_tampered_signature_fails() -> None:
    result = _verify(signature_header="v0=deadbeef")
    assert result.ok is False
    assert "signature mismatch" in result.reason


def test_stale_timestamp_fails() -> None:
    stale = _NOW - REPLAY_WINDOW_SECONDS - 1
    ts = int(stale)
    result = _verify(
        timestamp_header=str(ts),
        signature_header=sign(_SECRET, _BODY, ts),
        now=_NOW,
    )
    assert result.ok is False
    assert "replay window" in result.reason


def test_future_timestamp_fails() -> None:
    future = _NOW + REPLAY_WINDOW_SECONDS + 1
    ts = int(future)
    result = _verify(
        timestamp_header=str(ts),
        signature_header=sign(_SECRET, _BODY, ts),
        now=_NOW,
    )
    assert result.ok is False
    assert "replay window" in result.reason


def test_missing_timestamp_header_fails() -> None:
    result = _verify(timestamp_header=None)
    assert result.ok is False
    assert "missing signature headers" in result.reason


def test_missing_signature_header_fails() -> None:
    result = _verify(signature_header=None)
    assert result.ok is False
    assert "missing signature headers" in result.reason


def test_empty_signing_secret_fails() -> None:
    result = _verify(signing_secret=b"")
    assert result.ok is False
    assert "SLACK_SIGNING_SECRET" in result.reason


def test_non_numeric_timestamp_fails_without_raising() -> None:
    result = _verify(timestamp_header="not-a-number")
    assert result.ok is False
    assert "malformed timestamp" in result.reason


def test_wrong_signing_secret_fails() -> None:
    ts = int(_NOW)
    result = _verify(signature_header=sign(_OTHER_SECRET, _BODY, ts))
    assert result.ok is False
    assert "signature mismatch" in result.reason
