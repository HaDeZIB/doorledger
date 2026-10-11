"""Signed, rotating presence codes for DoorLedger check-in / check-out.

Each scheduled visit gets a 32-byte secret shared by the backend and the aide's
Caregiver Pass (it travels in the URL *fragment*, so it never reaches a server).
Every ``period`` seconds the pass shows a new code; the doorbell frame is
decoded and the backend verifies it with :func:`verify_code`.

QR payload (all characters are in the QR *alphanumeric* set, which keeps the
symbol small = bigger modules = readable from further away)::

    DL1.<VISIT_ID>.<STEP>.<MAC>

    VISIT_ID  [A-Z0-9-]{1,24}
    STEP      floor(unix_time / period), decimal
    MAC       base32 (RFC 4648, no padding) of the first ``mac_bytes`` bytes of
              HMAC-SHA256(secret, "DL1|<VISIT_ID>|<STEP>|<ROLE>")   ROLE = in|out

The role is *not* written in the payload; it is bound by the MAC, so a
check-in code can never be accepted as a check-out (pass ``role=None`` to
:func:`verify_code` to have it tell you which one it was).

Numeric fallback (for OCR / vision-model reading when the QR is unreadable):
an RFC 6238-style 6-digit TOTP (HMAC-SHA256, same period) keyed with a
role-specific subkey ``HMAC-SHA256(secret, "DL1|totp|<ROLE>")``.  It does not
carry the visit id, so the backend checks it only against the visits that are
expected at that doorbell right now.

The browser implementation in ``web/caregiver-pass/index.html`` must stay
byte-identical; ``core/tests/test_js_parity.py`` enforces that.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable, MutableSet
from dataclasses import dataclass

VERSION_TAG = "DL1"
DEFAULT_PERIOD = 15
DEFAULT_MAC_BYTES = 8  # 64-bit tag -> 13 base32 chars; online-verified, 15 s life
SECRET_BYTES = 32
ROLES = ("in", "out")

_VISIT_ID_RE = re.compile(r"^[A-Z0-9-]{1,24}$")
_CODE_RE = re.compile(r"^DL1\.([A-Z0-9-]{1,24})\.(\d{1,12})\.([A-Z2-7]{4,52})$")

SecretLookup = Callable[[str], bytes | None]
UsedSet = MutableSet[tuple[str, int, str]]


# --------------------------------------------------------------------------- helpers


def new_visit_secret() -> bytes:
    """Return a fresh 32-byte random visit secret."""
    return secrets.token_bytes(SECRET_BYTES)


def secret_to_b64url(secret: bytes) -> str:
    """Encode a secret for the Caregiver Pass URL fragment (``#k=...``)."""
    return base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")


def secret_from_b64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def current_step(at: float | None = None, period: int = DEFAULT_PERIOD) -> int:
    t = time.time() if at is None else at
    return int(t // period)


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")


def _check_visit_id(visit_id: str) -> None:
    if not _VISIT_ID_RE.match(visit_id):
        raise ValueError("visit_id must match [A-Z0-9-]{1,24} (QR alphanumeric set)")


def mac_message(visit_id: str, step: int, role: str) -> bytes:
    """The exact HMAC input. Shared contract with the JS pass."""
    return f"{VERSION_TAG}|{visit_id}|{step}|{role}".encode("ascii")


def _b32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def compute_mac(
    secret: bytes, visit_id: str, step: int, role: str, mac_bytes: int = DEFAULT_MAC_BYTES
) -> str:
    digest = hmac.new(secret, mac_message(visit_id, step, role), hashlib.sha256).digest()
    return _b32(digest[:mac_bytes])


# --------------------------------------------------------------------------- QR code


def make_code(
    visit_id: str,
    secret: bytes,
    role: str = "in",
    at: float | None = None,
    *,
    period: int = DEFAULT_PERIOD,
    mac_bytes: int = DEFAULT_MAC_BYTES,
) -> str:
    """Build the QR payload valid for the time step containing ``at`` (default now)."""
    _check_role(role)
    _check_visit_id(visit_id)
    if not 4 <= mac_bytes <= 32:
        raise ValueError("mac_bytes must be in [4, 32]")
    step = current_step(at, period)
    return f"{VERSION_TAG}.{visit_id}.{step}.{compute_mac(secret, visit_id, step, role, mac_bytes)}"


@dataclass(frozen=True, slots=True)
class PresenceResult:
    valid: bool
    reason: str  # "ok" | "malformed" | "unknown_visit" | "bad_mac" | "expired" |
    #              "not_yet_valid" | "replayed"
    visit_id: str | None = None
    role: str | None = None
    step: int | None = None
    skew: int | None = None  # code step - verifier step (0 = current window)

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.valid


def parse_code(code: str) -> tuple[str, int, str] | None:
    """Return ``(visit_id, step, mac)`` or ``None`` if the string is not a DL1 code."""
    m = _CODE_RE.match(code.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def verify_code(
    code: str,
    lookup_secret: SecretLookup | dict[str, bytes],
    role: str | None = "in",
    at: float | None = None,
    skew_steps: int = 1,
    *,
    period: int = DEFAULT_PERIOD,
    used: UsedSet | None = None,
    mark_used: bool = True,
) -> PresenceResult:
    """Verify a decoded QR payload.

    ``lookup_secret`` maps visit_id -> secret (callable or dict); return/contain
    ``None`` for unknown visits.  ``role=None`` accepts either role and reports
    which one matched.  ``skew_steps`` tolerates clock drift / capture latency
    (default +-1 step = +-15 s).

    Replay protection: pass a mutable set ``used`` of ``(visit_id, step, role)``.
    An already-present triple is rejected as ``replayed``; on success the triple
    is added (unless ``mark_used=False``).  Note a doorbell stream shows the same
    code in many consecutive frames, so dedupe per (visit, step, role) *before*
    calling with ``used`` if you want "first sighting" semantics.
    """
    parsed = parse_code(code)
    if parsed is None:
        return PresenceResult(False, "malformed")
    visit_id, step, mac = parsed

    secret = lookup_secret.get(visit_id) if isinstance(lookup_secret, dict) else lookup_secret(visit_id)
    if not secret:
        return PresenceResult(False, "unknown_visit", visit_id=visit_id, step=step)

    roles = ROLES if role is None else (role,)
    if role is not None:
        _check_role(role)

    # Only whole-byte truncations (as produced by make_code) of >= 4 bytes are accepted.
    n_bytes = len(mac) * 5 // 8
    if n_bytes < 4 or len(_b32(bytes(n_bytes))) != len(mac):
        return PresenceResult(False, "malformed", visit_id=visit_id, step=step)

    matched: str | None = None
    for r in roles:
        full = hmac.new(secret, mac_message(visit_id, step, r), hashlib.sha256).digest()
        if hmac.compare_digest(_b32(full[:n_bytes]).encode(), mac.encode()) and matched is None:
            matched = r
    if matched is None:
        return PresenceResult(False, "bad_mac", visit_id=visit_id, step=step)

    now_step = current_step(at, period)
    skew = step - now_step
    if skew < -skew_steps:
        return PresenceResult(False, "expired", visit_id, matched, step, skew)
    if skew > skew_steps:
        return PresenceResult(False, "not_yet_valid", visit_id, matched, step, skew)

    if used is not None:
        key = (visit_id, step, matched)
        if key in used:
            return PresenceResult(False, "replayed", visit_id, matched, step, skew)
        if mark_used:
            used.add(key)
    return PresenceResult(True, "ok", visit_id, matched, step, skew)


# --------------------------------------------------------------------------- compact numeric QR
#
# Spike S4 showed that pixels-per-module is THE limiting factor on a 150 deg
# doorbell lens.  The text form above needs QR version 2 (25 modules); this
# door-scoped numeric form fits version 1 (21 modules) at EC L/M/Q, i.e. ~20%
# bigger modules on the same phone screen.  It drops the visit id (the backend
# already knows which doorbell saw it and which visits are expected there) and
# sends only the low 4 digits of the step:
#
#     "1" + (step mod 10000, 4 digits) + (uint64 of mac[:8], 20 digits)  = 25 digits
#
# The MAC is the SAME HMAC-SHA256(secret, "DL1|<VISIT_ID>|<STEP>|<ROLE>") as the
# text form, so the visit id and role stay cryptographically bound.

COMPACT_PREFIX = "1"
_COMPACT_RE = re.compile(r"^1(\d{4})(\d{20})$")


def make_compact_code(
    visit_id: str,
    secret: bytes,
    role: str = "in",
    at: float | None = None,
    *,
    period: int = DEFAULT_PERIOD,
) -> str:
    """25-digit numeric QR payload (QR numeric mode -> version 1 at L/M/Q)."""
    _check_role(role)
    _check_visit_id(visit_id)
    step = current_step(at, period)
    digest = hmac.new(secret, mac_message(visit_id, step, role), hashlib.sha256).digest()
    return f"{COMPACT_PREFIX}{step % 10000:04d}{int.from_bytes(digest[:8], 'big'):020d}"


def _expand_step(low4: int, now_step: int) -> int:
    """Nearest step to ``now_step`` whose value mod 10000 equals ``low4``."""
    base = now_step - (now_step % 10000) + low4
    return min((base - 10000, base, base + 10000), key=lambda s: abs(s - now_step))


def verify_compact_code(
    code: str,
    candidates: dict[str, bytes],
    role: str | None = "in",
    at: float | None = None,
    skew_steps: int = 1,
    *,
    period: int = DEFAULT_PERIOD,
    used: UsedSet | None = None,
    mark_used: bool = True,
) -> PresenceResult:
    """Verify a compact numeric code against the visits expected at this door.

    ``candidates`` maps visit_id -> secret for the (few) visits scheduled at the
    doorbell that produced the frame.  Every candidate/role is checked so
    timing does not reveal which one matched.
    """
    m = _COMPACT_RE.match(code.strip())
    if not m:
        return PresenceResult(False, "malformed")
    if role is not None:
        _check_role(role)
    now_step = current_step(at, period)
    step = _expand_step(int(m.group(1)), now_step)
    mac = int(m.group(2))
    if mac >= 2**64:
        return PresenceResult(False, "malformed")
    got = mac.to_bytes(8, "big")
    roles = ROLES if role is None else (role,)
    hit: tuple[str, str] | None = None
    for vid, secret in candidates.items():
        for r in roles:
            exp = hmac.new(secret, mac_message(vid, step, r), hashlib.sha256).digest()[:8]
            if hmac.compare_digest(exp, got) and hit is None:
                hit = (vid, r)
    if hit is None:
        return PresenceResult(False, "bad_mac", step=step)
    vid, r = hit
    skew = step - now_step
    if skew < -skew_steps:
        return PresenceResult(False, "expired", vid, r, step, skew)
    if skew > skew_steps:
        return PresenceResult(False, "not_yet_valid", vid, r, step, skew)
    if used is not None:
        key = (vid, step, r)
        if key in used:
            return PresenceResult(False, "replayed", vid, r, step, skew)
        if mark_used:
            used.add(key)
    return PresenceResult(True, "ok", vid, r, step, skew)


# --------------------------------------------------------------------------- 6-digit fallback


def _totp_key(secret: bytes, role: str) -> bytes:
    return hmac.new(secret, f"{VERSION_TAG}|totp|{role}".encode("ascii"), hashlib.sha256).digest()


def _hotp(key: bytes, counter: int, digits: int = 6) -> str:
    """RFC 4226 HOTP with HMAC-SHA256 (as allowed by RFC 6238)."""
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def make_numeric_code(
    secret: bytes,
    role: str = "in",
    at: float | None = None,
    *,
    period: int = DEFAULT_PERIOD,
    digits: int = 6,
) -> str:
    """6-digit human-readable fallback for the same secret + role + time step."""
    _check_role(role)
    return _hotp(_totp_key(secret, role), current_step(at, period), digits)


def verify_numeric_code(
    digits_code: str,
    secret: bytes,
    role: str | None = "in",
    at: float | None = None,
    skew_steps: int = 1,
    *,
    period: int = DEFAULT_PERIOD,
    digits: int = 6,
    visit_id: str | None = None,
    used: UsedSet | None = None,
    mark_used: bool = True,
) -> PresenceResult:
    """Verify a 6-digit fallback code against ONE visit's secret.

    The caller supplies the candidate visit (the visits scheduled at this
    doorbell now); ``visit_id`` is only used for the replay key / result.
    With 6 digits and +-1 step there is a ~3e-6 chance a random guess matches,
    so the backend must also rate-limit attempts per doorbell.
    """
    code = digits_code.strip().replace(" ", "")
    if not (len(code) == digits and code.isdigit()):
        return PresenceResult(False, "malformed", visit_id=visit_id)
    if role is not None:
        _check_role(role)
    roles = ROLES if role is None else (role,)
    now_step = current_step(at, period)
    # Check every candidate (no early exit) to keep timing independent of the match.
    hit: tuple[str, int] | None = None
    for r in roles:
        key = _totp_key(secret, r)
        for skew in range(-skew_steps, skew_steps + 1):
            if now_step + skew < 0:
                continue
            match = hmac.compare_digest(_hotp(key, now_step + skew, digits).encode(), code.encode())
            if match and hit is None:
                hit = (r, skew)
    if hit is None:
        return PresenceResult(False, "bad_mac", visit_id=visit_id)
    r, skew = hit
    step = now_step + skew
    vid = visit_id or "?"
    if used is not None:
        key = (vid, step, r)
        if key in used:
            return PresenceResult(False, "replayed", visit_id, r, step, skew)
        if mark_used:
            used.add(key)
    return PresenceResult(True, "ok", visit_id, r, step, skew)


__all__ = [
    "DEFAULT_MAC_BYTES",
    "DEFAULT_PERIOD",
    "PresenceResult",
    "compute_mac",
    "current_step",
    "mac_message",
    "make_code",
    "make_compact_code",
    "make_numeric_code",
    "new_visit_secret",
    "parse_code",
    "secret_from_b64url",
    "secret_to_b64url",
    "verify_code",
    "verify_compact_code",
    "verify_numeric_code",
]
