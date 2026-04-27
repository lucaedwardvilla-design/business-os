"""Telegram notifier — sends draft preview via the existing Railway relay queue.

Relay endpoint pattern matches the Telegram bot's `_poll_relay_queue` flow.
The relay accepts a POST with a chat_id + text payload and queues it for the bot
to flush on next poll.

Falls back to direct Telegram Bot API if RELAY_URL is not set.
"""
from __future__ import annotations

import os

import httpx


def _relay_url() -> str:
    return os.environ.get("RELAY_URL", "").rstrip("/")


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _bot_poll_key() -> str:
    return os.environ.get("BOT_POLL_KEY", "")


async def send(chat_id: int, text: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    relay = _relay_url()
    poll_key = _bot_poll_key()
    if relay and poll_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{relay}/notify",
                    params={"bot_key": poll_key},
                    json={"chat_id": chat_id, "text": text},
                )
                if r.status_code == 200:
                    return True
        except Exception:
            pass

    # Fallback: direct Bot API
    token = _bot_token()
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text,
                      "disable_web_page_preview": True},
            )
            return r.status_code == 200
    except Exception:
        return False


def format_preview(*, client_name: str, post_id: int, title: str,
                   keyword: str, word_count: int, quality_score: int,
                   preview_url: str, edit_url: str) -> str:
    return (
        f"[SEO ENGINE] Draft ready — {client_name}\n\n"
        f"Title: {title}\n"
        f"Keyword: {keyword}\n"
        f"Words: {word_count} | Quality: {quality_score}/100\n\n"
        f"Preview: {preview_url}\n"
        f"Edit:    {edit_url}\n\n"
        f"Approve: /approve {client_name} {post_id}\n"
        f"Reject:  /reject {client_name} {post_id} <reason>"
    )
