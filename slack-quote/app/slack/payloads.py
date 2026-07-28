"""Parsing of the two payload shapes Slack sends us.

Both arrive as `application/x-www-form-urlencoded`. A slash command's fields are the
form itself; an interaction hides a JSON document inside a single `payload` field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs


@dataclass(frozen=True)
class SlashCommand:
    command: str
    text: str
    user_id: str
    user_name: str
    channel_id: str
    channel_name: str
    response_url: str


@dataclass(frozen=True)
class BlockAction:
    action_id: str
    value: str
    user_id: str
    user_name: str
    channel_id: str
    channel_name: str
    response_url: str


def _form(raw_body: bytes) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(raw_body.decode("utf-8")).items() if v}


def parse_slash_command(raw_body: bytes) -> SlashCommand:
    form = _form(raw_body)
    return SlashCommand(
        command=form.get("command", ""),
        text=form.get("text", ""),
        user_id=form.get("user_id", ""),
        user_name=form.get("user_name", ""),
        channel_id=form.get("channel_id", ""),
        channel_name=form.get("channel_name", ""),
        response_url=form.get("response_url", ""),
    )


def parse_block_action(raw_body: bytes) -> BlockAction | None:
    """Returns the first action in an interaction payload, or None if this is a kind
    of interaction we do not handle (a view submission, a shortcut, and so on)."""
    form = _form(raw_body)
    raw_payload = form.get("payload")
    if not raw_payload:
        return None
    try:
        payload: dict[str, Any] = json.loads(raw_payload)
    except ValueError:
        return None

    if payload.get("type") != "block_actions":
        return None
    actions = payload.get("actions") or []
    if not actions:
        return None

    action = actions[0]
    user = payload.get("user") or {}
    channel = payload.get("channel") or {}
    return BlockAction(
        action_id=str(action.get("action_id", "")),
        value=str(action.get("value", "")),
        user_id=str(user.get("id", "")),
        user_name=str(user.get("username") or user.get("name") or ""),
        channel_id=str(channel.get("id", "")),
        channel_name=str(channel.get("name", "")),
        # Each interaction carries its own fresh response_url; reusing the one from the
        # original command would burn that message's limited number of updates.
        response_url=str(payload.get("response_url", "")),
    )
