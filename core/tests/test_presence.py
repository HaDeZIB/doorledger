import base64
import hashlib
import hmac

import cv2
import numpy as np
import pytest
import segno
from doorledger import presence as p
from doorledger.presence_reader import PresenceReader

SECRET = bytes(range(32))
VID = "V7K2QX"
T0 = 1_760_200_000.0  # fixed timestamp


def lookup(vid):
    return {VID: SECRET}.get(vid)


def test_secret_roundtrip():
    s = p.new_visit_secret()
    assert len(s) == 32
    assert p.secret_from_b64url(p.secret_to_b64url(s)) == s
    assert "=" not in p.secret_to_b64url(s)


def test_code_format_and_known_vector():
    code = p.make_code(VID, SECRET, "in", at=T0)
    step = int(T0 // 15)
    assert code.startswith(f"DL1.{VID}.{step}.")
    mac = code.rsplit(".", 1)[1]
    assert len(mac) == 13  # 8 bytes base32
    digest = hmac.new(SECRET, f"DL1|{VID}|{step}|in".encode(), hashlib.sha256).digest()
    assert mac == base64.b32encode(digest[:8]).decode().rstrip("=")
    # whole payload is QR-alphanumeric -> compact symbol
    assert segno.make(code, error="m").mode == "alphanumeric"
    assert segno.make(code, error="m").version <= 2


def test_verify_ok_and_role_binding():
    code = p.make_code(VID, SECRET, "in", at=T0)
    r = p.verify_code(code, lookup, "in", at=T0)
    assert r.valid and r.reason == "ok" and r.visit_id == VID and r.role == "in" and r.skew == 0
    assert p.verify_code(code, lookup, "out", at=T0).reason == "bad_mac"
    auto = p.verify_code(code, lookup, None, at=T0)
    assert auto.valid and auto.role == "in"
    out = p.make_code(VID, SECRET, "out", at=T0)
    assert p.verify_code(out, lookup, None, at=T0).role == "out"
    assert out != code


def test_dict_lookup_and_unknown_visit():
    code = p.make_code(VID, SECRET, "in", at=T0)
    assert p.verify_code(code, {VID: SECRET}, at=T0).valid
    assert p.verify_code(code, {}, at=T0).reason == "unknown_visit"


@pytest.mark.parametrize(
    "dt,ok,reason",
    [(0, True, "ok"), (14.9, True, "ok"), (-15, True, "ok"), (15, True, "ok"),
     (30, False, "expired"), (-30, False, "not_yet_valid")],
)
def test_skew_window(dt, ok, reason):
    at = (T0 // 15) * 15  # start of a step
    code = p.make_code(VID, SECRET, "in", at=at)
    r = p.verify_code(code, lookup, "in", at=at + dt)
    assert r.valid is ok and r.reason == reason


def test_tamper_and_malformed():
    code = p.make_code(VID, SECRET, "in", at=T0)
    head, mac = code.rsplit(".", 1)
    flipped = head + "." + ("A" if mac[0] != "A" else "B") + mac[1:]
    assert p.verify_code(flipped, lookup, at=T0).reason == "bad_mac"
    other_step = code.replace(f".{int(T0 // 15)}.", f".{int(T0 // 15) + 1}.")
    assert p.verify_code(other_step, lookup, at=T0).reason == "bad_mac"
    assert p.verify_code(p.make_code(VID, b"x" * 32, "in", at=T0), lookup, at=T0).reason == "bad_mac"
    for bad in ["", "hello", "DL2.V.1.AAAAAAAA", f"DL1.{VID.lower()}.1.AAAAAAAAAAAAA",
                f"DL1.{VID}.1.ABC", head + "." + mac[:-2]]:
        assert p.verify_code(bad, lookup, at=T0).reason == "malformed", bad


def test_replay_protection():
    used: set = set()
    code = p.make_code(VID, SECRET, "in", at=T0)
    assert p.verify_code(code, lookup, at=T0, used=used).valid
    assert p.verify_code(code, lookup, at=T0 + 1, used=used).reason == "replayed"
    # mark_used=False only checks
    used2: set = set()
    assert p.verify_code(code, lookup, at=T0, used=used2, mark_used=False).valid
    assert not used2
    # next step is a new code -> accepted
    nxt = p.make_code(VID, SECRET, "in", at=T0 + 15)
    assert p.verify_code(nxt, lookup, at=T0 + 15, used=used).valid


def test_input_validation():
    with pytest.raises(ValueError):
        p.make_code("lower", SECRET, "in")
    with pytest.raises(ValueError):
        p.make_code("V.1", SECRET, "in")
    with pytest.raises(ValueError):
        p.make_code(VID, SECRET, "maybe")
    with pytest.raises(ValueError):
        p.make_numeric_code(SECRET, "maybe")


def test_mac_bytes_variants_verify():
    for n in (4, 5, 8, 10, 16, 32):
        code = p.make_code(VID, SECRET, "out", at=T0, mac_bytes=n)
        assert p.verify_code(code, lookup, "out", at=T0).valid, n


# ------------------------------------------------------------------ numeric fallback


def test_numeric_code_rfc6238_sha256_vector():
    # RFC 6238 Appendix B, SHA256 seed, T=59 -> 46119246 (8 digits), period 30.
    seed = b"12345678901234567890123456789012"
    assert p._hotp(seed, 59 // 30, 8) == "46119246"
    assert p._hotp(seed, 1111111109 // 30, 8) == "68084774"


def test_numeric_code_verify():
    c_in = p.make_numeric_code(SECRET, "in", at=T0)
    c_out = p.make_numeric_code(SECRET, "out", at=T0)
    assert len(c_in) == 6 and c_in.isdigit() and c_in != c_out
    assert p.verify_numeric_code(c_in, SECRET, "in", at=T0).valid
    assert p.verify_numeric_code(c_in, SECRET, "in", at=T0 + 15).valid  # skew 1
    assert p.verify_numeric_code(c_in, SECRET, "in", at=T0 + 45).reason == "bad_mac"
    assert p.verify_numeric_code(c_in, SECRET, None, at=T0).role == "in"
    assert p.verify_numeric_code("12a456", SECRET, at=T0).reason == "malformed"
    assert p.verify_numeric_code(c_in[:3] + " " + c_in[3:], SECRET, at=T0).valid
    used: set = set()
    assert p.verify_numeric_code(c_in, SECRET, at=T0, visit_id=VID, used=used).valid
    assert p.verify_numeric_code(c_in, SECRET, at=T0, visit_id=VID, used=used).reason == "replayed"


# ------------------------------------------------------------------ reader


def _qr_image(text, scale=8, border=4, error="m"):
    q = segno.make(text, error=error, micro=False)
    m = np.array(q.matrix, dtype=np.uint8)
    m = np.pad(m, border)
    img = np.where(m == 1, 0, 255).astype(np.uint8)
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def test_reader_decodes_and_verifies_in_frame():
    code = p.make_code(VID, SECRET, "in", at=T0)
    qr = _qr_image(code, scale=6)
    frame = np.full((1080, 1920, 3), 90, np.uint8)
    y, x = 500, 900
    frame[y : y + qr.shape[0], x : x + qr.shape[1]] = qr[..., None]
    res = PresenceReader().read(frame)
    assert code in res.texts
    d = res.detections[0]
    bx, by, _bw, _bh = d.bbox
    assert abs(bx - (x + 24)) < 12 and abs(by - (y + 24)) < 12
    assert p.verify_code(res.texts[0], lookup, at=T0).valid


def test_reader_small_code_uses_upscale():
    code = p.make_code(VID, SECRET, "in", at=T0)
    qr = _qr_image(code, scale=2)  # ~2 px/module, blurred
    qr = cv2.GaussianBlur(cv2.resize(qr, None, fx=1.3, fy=1.3), (3, 3), 0.6)
    frame = np.full((1080, 1920), 60, np.uint8)
    frame[400 : 400 + qr.shape[0], 1000 : 1000 + qr.shape[1]] = qr
    res = PresenceReader().read(frame)
    assert code in res.texts, res.stages_tried


def test_reader_empty_frame():
    frame = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    res = PresenceReader().read(frame)
    assert res.detections == []


# ------------------------------------------------------------------ compact numeric QR


def test_compact_code_format_and_qr_version():
    c = p.make_compact_code(VID, SECRET, "in", at=T0)
    step = int(T0 // 15)
    assert len(c) == 25 and c.isdigit() and c[0] == "1" and c[1:5] == f"{step % 10000:04d}"
    digest = hmac.new(SECRET, f"DL1|{VID}|{step}|in".encode(), hashlib.sha256).digest()
    assert int(c[5:]) == int.from_bytes(digest[:8], "big")
    for ec in "lmq":
        q = segno.make(c, error=ec, micro=False, boost_error=False)
        assert q.version == 1 and q.mode == "numeric"


def test_compact_code_verify():
    cands = {VID: SECRET, "OTHER": b"o" * 32}
    c = p.make_compact_code(VID, SECRET, "out", at=T0)
    r = p.verify_compact_code(c, cands, None, at=T0)
    assert r.valid and r.visit_id == VID and r.role == "out"
    assert p.verify_compact_code(c, cands, "in", at=T0).reason == "bad_mac"
    assert p.verify_compact_code(c, {"OTHER": b"o" * 32}, "out", at=T0).reason == "bad_mac"
    assert p.verify_compact_code(c, cands, "out", at=T0 + 15).valid
    assert p.verify_compact_code(c, cands, "out", at=T0 + 31).reason == "expired"
    assert p.verify_compact_code(c[:-1], cands, at=T0).reason == "malformed"
    assert p.verify_compact_code("2" + c[1:], cands, at=T0).reason == "malformed"
    used: set = set()
    assert p.verify_compact_code(c, cands, "out", at=T0, used=used).valid
    assert p.verify_compact_code(c, cands, "out", at=T0, used=used).reason == "replayed"


def test_compact_code_step_wraparound():
    # step whose low 4 digits roll over 9999 -> 0000 between code and verifier
    at = 15 * (10000 * 11734 + 9999)
    c = p.make_compact_code(VID, SECRET, "in", at=at)
    assert c[1:5] == "9999"
    r = p.verify_compact_code(c, {VID: SECRET}, "in", at=at + 15)
    assert r.valid and r.skew == -1
    c2 = p.make_compact_code(VID, SECRET, "in", at=at + 15)
    assert c2[1:5] == "0000"
    assert p.verify_compact_code(c2, {VID: SECRET}, "in", at=at).valid
