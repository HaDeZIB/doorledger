"""Outbound channels. Every message is also written to the ledger as an Action."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol
from xml.sax.saxutils import escape

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


def demo_envelope(person: Person, message: str) -> str:
    """Every demo SMS lands on one test phone, so it says who it was for. Short, no brand name
    and no arrow: the patient would get the bare message in production."""
    first = person.name.split()[0]
    return f"[Demo · {'para' if person.language == 'es' else 'for'} {first}] {message}"


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
                Message=demo_envelope(person, message)[:600],
                MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String",
                                                          "StringValue": "Transactional"}},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - a failed SMS must not break the engine
            log.warning("sns send failed: %s", exc)
            return False


class ConnectVoiceNotifier:
    """Real outbound voice call through Amazon Connect (the patient's primary channel).

    The contact flow (``DOORLEDGER_CONNECT_FLOW_ID``) speaks the contact attribute ``ssml`` with
    a neural Spanish voice and hangs up. Active only when the instance, flow, caller id and
    destination are all set. Demo safety: every call goes to the one verified test phone in
    ``DOORLEDGER_VOICE_TO``, never to a household member's number.

    Placing a call never blocks or breaks the ladder: errors are logged and reported as "not
    placed", and the responder falls back to SMS. Whether the call was answered is learned
    afterwards by polling ``describe_contact`` on a daemon thread (``watch``).
    """

    channel = "voice"

    def __init__(self, *, instance_id: str | None = None, flow_id: str | None = None,
                 source: str | None = None, to: str | None = None, region: str | None = None,
                 client: Any = None, poll_for_s: float = 120.0, poll_every_s: float = 4.0,
                 spawn: Callable[[Callable[[], None]], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        env = os.environ.get
        self.instance_id = instance_id or env("DOORLEDGER_CONNECT_INSTANCE_ID", "")
        self.flow_id = flow_id or env("DOORLEDGER_CONNECT_FLOW_ID", "")
        self.source = source or env("DOORLEDGER_CONNECT_SOURCE_NUMBER", "")
        self.to = to or env("DOORLEDGER_VOICE_TO", "")
        self.region = region or env("DOORLEDGER_CONNECT_REGION", env("AWS_REGION", "us-east-1"))
        self._client = client
        self.poll_for_s, self.poll_every_s = poll_for_s, poll_every_s
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        return bool(self.instance_id and self.flow_id and self.source and self.to)

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("connect", region_name=self.region)
        return self._client

    def call(self, person: Person, ssml: str) -> str | None:
        """Place the call; returns the Connect contact id, or None if it was not placed."""
        if not self.enabled:
            return None
        try:
            r = self.client.start_outbound_voice_contact(
                InstanceId=self.instance_id, ContactFlowId=self.flow_id,
                DestinationPhoneNumber=self.to, SourcePhoneNumber=self.source,
                Attributes={"ssml": ssml})
            log.info("[call → %s] contact %s", person.name, r.get("ContactId"))
            return r.get("ContactId") or None
        except Exception as exc:  # noqa: BLE001 - a failed call must not break the engine
            log.warning("connect call failed: %s", str(exc)[:200])
            return None

    def send(self, person: Person, message: str) -> bool:
        """Notifier protocol: speak a plain-text message slowly."""
        ssml = f'<speak><prosody rate="88%">{escape(message)}</prosody></speak>'
        return self.call(person, ssml) is not None

    def status(self, contact_id: str) -> str | None:
        """"answered" | "no_answer" once known, else None (still ringing, or unknown)."""
        try:
            c = self.client.describe_contact(InstanceId=self.instance_id,
                                             ContactId=contact_id)["Contact"]
        except Exception as exc:  # noqa: BLE001
            log.warning("connect describe_contact failed: %s", str(exc)[:200])
            return None
        if c.get("ConnectedToSystemTimestamp"):
            return "answered"
        if c.get("DisconnectTimestamp"):
            return "no_answer"
        return None

    def watch(self, contact_id: str, on_status: Callable[[str], None]) -> None:
        """Poll in the background until the call is answered or ends unanswered."""

        def poll() -> None:
            waited = 0.0
            while waited < self.poll_for_s:
                self._sleep(self.poll_every_s)
                waited += self.poll_every_s
                st = self.status(contact_id)
                if st:
                    try:
                        on_status(st)
                    except Exception:
                        log.exception("call status callback failed")
                    return

        self._spawn(poll)


def default_voice() -> ConnectVoiceNotifier | None:
    v = ConnectVoiceNotifier()
    return v if v.enabled else None


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


def channel_fields(person: Person, notifier: Notifier, channel: str | None = None) -> dict[str, str]:
    """What an Action records about delivery.

    ``channel`` is how the household chose to reach this person for this message (Rosa: a
    voice call plus an SMS); ``via`` is the notifier that actually carried it: "voice" (Amazon
    Connect), "sms" (Amazon SNS), "telegram", or "app" (console only: the dashboard shows it,
    nothing left this machine).
    """
    via = getattr(notifier, "channel", "app")
    return {"channel": channel or person.channel or via, "via": via}


def default_notifier() -> Notifier:
    extra = [n for n in (SNSNotifier(), TelegramNotifier()) if n.enabled]
    if not extra:
        return ConsoleNotifier()
    fan = FanOutNotifier(ConsoleNotifier(), *extra)
    fan.channel = extra[0].channel  # shown on the dashboard ("sms" when SNS is on)
    return fan
