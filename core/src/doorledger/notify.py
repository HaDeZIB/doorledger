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


class SNSNotifier:
    """Real SMS through Amazon SNS. For the demo every household member maps to one verified
    phone (SNS sandbox), and the message is prefixed with who it was for."""

    channel = "sms"

    def __init__(self, phone: str | None = None, region: str | None = None) -> None:
        self.phone = phone or os.environ.get("DOORLEDGER_SMS_TO", "")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.phone)

    def send(self, person: Person, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            if self._client is None:
                import boto3

                self._client = boto3.client("sns", region_name=self.region)
            self._client.publish(
                PhoneNumber=person.phone or self.phone,
                Message=f"DoorLedger → {person.name}: {message}"[:600],
                MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String",
                                                          "StringValue": "Transactional"}},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - a failed SMS must not break the engine
            log.warning("sns send failed: %s", exc)
            return False


class FanOutNotifier:
    channel = "app"

    def __init__(self, *notifiers: Notifier) -> None:
        self.notifiers = [n for n in notifiers if getattr(n, "enabled", True)]

    def send(self, person: Person, message: str) -> bool:
        """Delivered = at least one REAL channel (SMS/Telegram) succeeded; the console log
        only counts when it is the sole channel."""
        real = [n for n in self.notifiers if not isinstance(n, ConsoleNotifier)]
        results = {id(n): n.send(person, message) for n in self.notifiers}
        if real:
            return any(results[id(n)] for n in real)
        return any(results.values())


def channel_fields(person: Person, notifier: Notifier) -> dict[str, str]:
    """What an Action records about delivery.

    ``channel`` is how the household chose to reach this person (Rosa: SMS, she uses no app);
    ``via`` is the notifier that actually carried the message: "sms" (Amazon SNS), "telegram",
    or "app" (console only: the dashboard shows it, nothing left this machine).
    """
    via = getattr(notifier, "channel", "app")
    return {"channel": person.channel or via, "via": via}


def default_notifier() -> Notifier:
    extra = [n for n in (SNSNotifier(), TelegramNotifier()) if n.enabled]
    if not extra:
        return ConsoleNotifier()
    fan = FanOutNotifier(ConsoleNotifier(), *extra)
    fan.channel = extra[0].channel  # shown on the dashboard ("sms" when SNS is on)
    return fan
