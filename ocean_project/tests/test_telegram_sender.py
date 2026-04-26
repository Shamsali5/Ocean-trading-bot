"""Tests for Telegram sender transport helpers."""

from __future__ import annotations

from typing import Any

import pytest

from ocean_engine.output import telegram_sender


class _DummyResponse:
    def __init__(self, payload: dict[str, Any], ok: bool = True) -> None:
        self._payload = payload
        self.ok = ok

    def json(self) -> dict[str, Any]:
        return self._payload


def test_missing_token_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        telegram_sender.get_telegram_credentials()


def test_missing_chat_id_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        telegram_sender.get_telegram_credentials()


def test_short_message_does_not_split() -> None:
    text = "short message"
    assert telegram_sender.split_telegram_message(text, max_length=3900) == [text]


def test_long_message_splits_into_multiple_parts() -> None:
    text = ("line\n" * 2000).strip()
    chunks = telegram_sender.split_telegram_message(text, max_length=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_split_preserves_all_content_when_joined() -> None:
    text = "".join(f"row-{idx}\n" for idx in range(300))
    chunks = telegram_sender.split_telegram_message(text, max_length=73)
    assert "".join(chunks) == text


def test_send_uses_provided_credentials_without_env_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_env_lookup() -> tuple[str, str]:
        raise AssertionError("env lookup should not be called")

    monkeypatch.setattr(telegram_sender, "get_telegram_credentials", _unexpected_env_lookup)
    monkeypatch.setattr(
        telegram_sender.requests,
        "post",
        lambda *_args, **_kwargs: _DummyResponse({"ok": True, "result": {"message_id": 1}}),
    )

    result = telegram_sender.send_telegram_message("hello", bot_token="token", chat_id="chat")
    assert result == [{"ok": True, "result": {"message_id": 1}}]


def test_send_posts_expected_url_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_post(url: str, json: dict[str, Any], timeout: int) -> _DummyResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _DummyResponse({"ok": True, "result": {"message_id": len(calls)}})

    monkeypatch.setattr(telegram_sender.requests, "post", _fake_post)

    text = "A" * 300
    responses = telegram_sender.send_telegram_message(
        text,
        bot_token="bot-token",
        chat_id="chat-id",
    )

    assert len(calls) >= 1
    assert len(responses) == len(calls)
    assert all(call["url"] == "https://api.telegram.org/botbot-token/sendMessage" for call in calls)
    assert all(call["json"]["chat_id"] == "chat-id" for call in calls)
    assert all("parse_mode" not in call["json"] for call in calls)
    assert all(call["timeout"] == 15 for call in calls)
    assert "".join(call["json"]["text"] for call in calls) == text


def test_telegram_error_response_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        telegram_sender.requests,
        "post",
        lambda *_args, **_kwargs: _DummyResponse(
            {"ok": False, "description": "Bad Request: chat not found"},
            ok=True,
        ),
    )

    with pytest.raises(RuntimeError, match="Telegram API error"):
        telegram_sender.send_telegram_message("hello", bot_token="token", chat_id="chat")
