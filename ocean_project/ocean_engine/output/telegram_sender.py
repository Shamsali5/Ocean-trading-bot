"""Telegram transport helpers for already-formatted report text."""

from __future__ import annotations

import os
from typing import Any

from ocean_engine.utils import http_client as requests


def get_telegram_credentials() -> tuple[str, str]:
    """Return Telegram bot token and chat ID from environment."""

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    if not chat_id:
        raise ValueError("Missing TELEGRAM_CHAT_ID environment variable.")
    return bot_token, chat_id


def split_telegram_message(text: str, max_length: int = 3900) -> list[str]:
    """Split a message into Telegram-safe chunks without dropping content."""

    if max_length <= 0:
        raise ValueError("max_length must be greater than zero.")
    if len(text) <= max_length:
        return [text]

    parts: list[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        window_end = min(start + max_length, text_length)
        if window_end == text_length:
            parts.append(text[start:window_end])
            break

        split_index = text.rfind("\n", start, window_end)
        if split_index == -1:
            parts.append(text[start:window_end])
            start = window_end
            continue

        # Keep the newline in the previous chunk so content is preserved.
        part_end = split_index + 1
        parts.append(text[start:part_end])
        start = part_end
    return parts


def send_telegram_message(
    text: str,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    """Send one message (split into parts as needed) via Telegram Bot API."""

    resolved_token = (bot_token or "").strip()
    resolved_chat_id = (chat_id or "").strip()
    if not resolved_token or not resolved_chat_id:
        env_token, env_chat_id = get_telegram_credentials()
        if not resolved_token:
            resolved_token = env_token
        if not resolved_chat_id:
            resolved_chat_id = env_chat_id

    url = f"https://api.telegram.org/bot{resolved_token}/sendMessage"
    responses: list[dict[str, Any]] = []
    for part in split_telegram_message(text):
        payload = {
            "chat_id": resolved_chat_id,
            "text": part,
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            response_data = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("Telegram API returned non-JSON response.") from exc

        if not response.ok:
            description = (
                response_data.get("description", "unknown Telegram HTTP error")
                if isinstance(response_data, dict)
                else "unknown Telegram HTTP error"
            )
            raise RuntimeError(f"Telegram API HTTP error: {description}")

        if not isinstance(response_data, dict) or not response_data.get("ok", False):
            description = (
                response_data.get("description", "unknown Telegram API error")
                if isinstance(response_data, dict)
                else "unknown Telegram API error"
            )
            raise RuntimeError(f"Telegram API error: {description}")

        responses.append(response_data)
    return responses
