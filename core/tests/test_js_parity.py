"""The Caregiver Pass (web/caregiver-pass/index.html) must produce byte-identical
codes to doorledger.presence, and its inline QR encoder must produce symbols
OpenCV can decode.  The JS is extracted verbatim from the shipped page and run
under node, so what is tested is exactly what ships."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
import segno
from doorledger import presence as p

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "web" / "caregiver-pass" / "index.html"
NODE = shutil.which("node") or "/usr/local/bin/node"

pytestmark = pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")


def _block(name: str) -> str:
    html = PAGE.read_text()
    m = re.search(rf"/\* BEGIN {name}.*?\*/(.*?)/\* END {name} \*/", html, re.DOTALL)
    assert m, f"block {name} not found in {PAGE}"
    return m.group(1)


def _run_node(tmp_path: Path, body: str, payload: object) -> object:
    script = tmp_path / "run.mjs"
    script.write_text(
        _block("DL-PRESENCE") + "\n" + _block("DL-QR") + "\n"
        "const input = JSON.parse(process.argv[2]);\n" + body
    )
    out = subprocess.run([NODE, str(script), json.dumps(payload)], capture_output=True,
                         text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


TIMES = [0, 14.999, 15, 1_760_200_000, 1_760_200_007.5, 1_760_200_014.9999,
         1_893_456_000, 2_000_000_000.25, 4_102_444_800]
SECRETS = [bytes(range(32)), bytes(32), b"\xff" * 32, bytes.fromhex(
    "8f1c6b0a2d4e9f3a7b5c1d0e2f4a6b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d5e6")]
VISITS = ["V7K2QX", "A", "CLIENT0042-VISIT-2026101", "0-0-0"]


def test_codes_byte_identical(tmp_path):
    cases = []
    for i, t in enumerate(TIMES):
        for j, secret in enumerate(SECRETS):
            for role in ("in", "out"):
                vid = VISITS[(i + j) % len(VISITS)]
                mac_bytes = (8, 10, 16, 4)[(i + j) % 4]
                cases.append({"t": t, "k": p.secret_to_b64url(secret), "v": vid, "role": role,
                              "mb": mac_bytes})
    js = _run_node(tmp_path, """
const out = [];
for (const c of input) {
  const k = DL.b64urlToBytes(c.k);
  out.push({
    text: await DL.makeCode(c.v, k, c.role, c.t, c.mb),
    compact: await DL.makeCompactCode(c.v, k, c.role, c.t),
    digits: await DL.makeNumericCode(k, c.role, c.t),
  });
}
console.log(JSON.stringify(out));
""", cases)
    assert len(js) == len(cases)
    for c, got in zip(cases, js):
        secret = p.secret_from_b64url(c["k"])
        assert got["text"] == p.make_code(c["v"], secret, c["role"], at=c["t"],
                                          mac_bytes=c["mb"]), c
        assert got["compact"] == p.make_compact_code(c["v"], secret, c["role"], at=c["t"]), c
        assert got["digits"] == p.make_numeric_code(secret, c["role"], at=c["t"]), c
        # and the backend accepts what the page shows
        assert p.verify_code(got["text"], {c["v"]: secret}, c["role"], at=c["t"]).valid
        assert p.verify_compact_code(got["compact"], {c["v"]: secret}, c["role"], at=c["t"]).valid
        assert p.verify_numeric_code(got["digits"], secret, c["role"], at=c["t"]).valid


def test_base32_matches_python(tmp_path):
    import base64
    import os

    blobs = [os.urandom(n) for n in range(34)]
    js = _run_node(tmp_path, """
console.log(JSON.stringify(input.map(h => DL.base32(Uint8Array.from(Buffer.from(h, 'hex'))))));
""", [b.hex() for b in blobs])
    assert js == [base64.b32encode(b).decode().rstrip("=") for b in blobs]


def _matrix_to_img(mods: list[list[bool]], scale: int = 8, quiet: int = 4) -> np.ndarray:
    m = np.pad(np.array(mods, dtype=np.uint8), quiet)
    img = np.where(m == 1, 0, 255).astype(np.uint8)
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def test_js_qr_encoder_decodes_with_opencv(tmp_path):
    secret = bytes(range(32))
    payloads = [
        p.make_compact_code("V7K2QX", secret, "in", at=1_760_200_000),
        p.make_code("V7K2QX", secret, "out", at=1_760_200_000),
        p.make_code("CLIENT0042-VISIT-2026101", secret, "in", at=1_760_200_000, mac_bytes=16),
        "HELLO WORLD",
        "https://example.com/doorledger?x=1",  # byte mode
        "0123456789" * 9,  # longer numeric
        "Ünïcödé ✓",
    ]
    cases = [{"text": t, "ec": ec} for t in payloads for ec in "LMQH"]
    js = _run_node(tmp_path, """
console.log(JSON.stringify(input.map(c => QR.encode(c.text, c.ec))));
""", cases)
    det = cv2.QRCodeDetector()
    for c, q in zip(cases, js):
        ref = segno.make(c["text"], error=c["ec"].lower(), micro=False, boost_error=False)
        assert q["version"] == ref.version, (c, q["version"], ref.version)
        text, _, _ = det.detectAndDecode(_matrix_to_img(q["modules"]))
        assert text == c["text"], c
    # also with the 2-module quiet zone the page actually renders
    q = js[cases.index({"text": payloads[0], "ec": "M"})]
    text, _, _ = det.detectAndDecode(np.pad(_matrix_to_img(q["modules"], quiet=2), 40,
                                            constant_values=255))
    assert text == payloads[0]
    assert q["version"] == 1


def test_js_qr_matches_segno_for_same_mask(tmp_path):
    """Stronger than decodability: with the same mask, modules must be identical."""
    secret = bytes(range(32))
    payloads = [p.make_compact_code("V7K2QX", secret, r, at=1_760_200_000 + 15 * i)
                for i in range(4) for r in ("in", "out")]
    payloads += [p.make_code("V7K2QX", secret, "in", at=1_760_200_000)]
    cases = [{"text": t, "ec": ec} for t in payloads for ec in "LMQ"]
    js = _run_node(tmp_path, """
console.log(JSON.stringify(input.map(c => QR.encode(c.text, c.ec))));
""", cases)
    for c, q in zip(cases, js):
        ref = segno.make(c["text"], error=c["ec"].lower(), micro=False, boost_error=False,
                         mask=q["mask"])
        assert np.array_equal(np.array(ref.matrix, dtype=bool), np.array(q["modules"])), c
