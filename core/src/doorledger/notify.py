"""Outbound channels. Every message is also written to the ledger as an Action."""

from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from .domain import Person

log = logging.getLogger("doorledger.notify")


class Notifier(Protocol):
    channel: str

    def send(self, person: Person, message: str) -> bool: ...


class ConsoleNotifier:
    """Demo default: prints and reports delivered. The dashboard shows the message."""

    channel = "app"

    def send(self, person: Person, message: str) -> bool:
        log.info("[notify → %s] %s", person.name, message)
        return True


class TelegramNotifier:
    """Sends real messages to one demo phone (Brandon's) so the video shows a phone buzzing.

    All people in the demo household map to the same chat, prefixed with who it was "for".
    """

    channel = "telegram"

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, person: Person, message: str) -> bool:
        if not self.enabled:
            return False
        chat = person.telegram_chat_id or self.chat_id
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat, "text": f"DoorLedger → {person.name}\n\n{message}"},
                timeout=10,
            )
            return r.status_code == 200
        except httpx.HTTPError as exc:  # pragma: no cover - network
            log.warning("telegram send failed: %s", exc)
            return False


class FanOutNotifier:
    channel = "app"

    def __init__(self, *notifiers: Notifier) -> None:
        self.notifiers = [n for n in notifiers if getattr(n, "enabled", True)]

    def send(self, person: Person, message: str) -> bool:
        results = [n.send(person, message) for n in self.notifiers]
        return any(results)


def default_notifier() -> Notifier:
    tg = TelegramNotifier()
    return FanOutNotifier(ConsoleNotifier(), tg) if tg.enabled else ConsoleNotifier()
