"""Spike S4 evaluation: decode rate of presence QRs in synthetic doorbell frames.

    uv run python eval/presence/run_eval.py            # full run (~3-6 min, all cores)
    uv run python eval/presence/run_eval.py --quick    # smoke run

Writes eval/presence/results.json and eval/presence/RESULTS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "core" / "src"))

import numpy as np
from doorledger.presence import (
    make_code,
    make_compact_code,
    make_numeric_code,
    verify_code,
    verify_compact_code,
)
from doorledger.presence_reader import PresenceReader
from make_synthetic import (
    CONDITIONS,
    DISTANCES,
    EC_LEVELS,
    SceneParams,
    focal_px,
    qr_modules,
    qr_version,
    render,
)

SECRET = bytes(range(32))
T0 = 1_760_200_000.0
VID = "V7K2QX"
LONG_VID = "CLIENT0042-VISIT-2026101"
# name -> (description, quiet-zone modules)
FORMATS = {
    "num_qz2": ("compact numeric, 25 digits, quiet zone 2 (RECOMMENDED)", 2),
    "num_qz4": ("compact numeric, 25 digits, quiet zone 4", 4),
    "text_qz4": ("DL1 text, 6-char visit id, 64-bit MAC, 34 chars, quiet zone 4", 4),
    "long_qz4": ("DL1 text, 24-char visit id, 128-bit MAC, 62 chars, quiet zone 4", 4),
}
MAIN_FORMAT = "num_qz2"

_reader: PresenceReader | None = None


def _payload(fmt: str, step_offset: int) -> str:
    at = T0 + 15 * step_offset
    if fmt.startswith("num"):
        return make_compact_code(VID, SECRET, "in", at=at)
    if fmt.startswith("text"):
        return make_code(VID, SECRET, "in", at=at, mac_bytes=8)
    return make_code(LONG_VID, SECRET, "in", at=at, mac_bytes=16)


def _verify(fmt: str, text: str, at: float) -> bool:
    if fmt.startswith("num"):
        return verify_compact_code(text, {VID: SECRET, LONG_VID: SECRET[::-1]}, "in", at=at).valid
    return verify_code(text, {VID: SECRET, LONG_VID: SECRET}, "in", at=at).valid


def _scene(task: dict, jitter: int | None = None) -> tuple[SceneParams, str, float]:
    step = task["seed"] % 1000
    at = T0 + 15 * step
    payload = _payload(task["fmt"], step)
    sp = SceneParams(payload=payload, digits=make_numeric_code(SECRET, "in", at=at),
                     ec=task["ec"], resolution=task["resolution"],
                     distance_m=task["distance"], qr_size_cm=task.get("qr_cm"),
                     quiet=FORMATS[task["fmt"]][1], condition=task["condition"],
                     seed=task["seed"], jitter_seed=jitter)
    return sp, payload, at


def run_trial(task: dict) -> dict:
    global _reader
    if _reader is None:
        # No time budget in the grid: workers share the CPU, so a wall-clock budget
        # would make accuracy depend on contention. Latency is measured separately
        # (single process, default 250 ms budget) in benchmark().
        _reader = PresenceReader(time_budget_ms=float("inf"))
    frames = task.get("burst", 1)
    hits = 0
    first_hit = None
    ms = []
    stage = ""
    false_reads = 0
    meta = {}
    for j in range(frames):
        sp, payload, at = _scene(task, None if frames == 1 else task["seed"] * 100 + j)
        frame, meta = render(sp)
        res = _reader.read(frame)
        ms.append(res.elapsed_ms)
        good = [t for t in res.texts if t == payload and _verify(task["fmt"], t, at)]
        false_reads += sum(1 for t in res.texts if t != payload)
        if good:
            hits += 1
            if first_hit is None:
                first_hit = j
                stage = next(d.stage for d in res.detections if d.text == payload)
    return {**task, "ok": hits > 0, "frame_hits": hits, "first_hit": first_hit,
            "false_reads": false_reads, "ms": statistics.mean(ms), "stage": stage,
            "px_per_module": meta["px_per_module"], "qr_px": meta["qr_px"],
            "digit_height_px": meta["digit_height_px"], "qr_version": meta["qr_version"]}


def build_tasks(n: int, quick: bool) -> list[dict]:
    tasks: list[dict] = []
    seed = 0

    def add(reps=n, **kw):
        nonlocal seed
        for _ in range(reps):
            seed += 1
            tasks.append({**kw, "seed": seed})

    dists = DISTANCES if not quick else (0.4, 0.75, 1.0)
    conds = CONDITIONS if not quick else ("clean", "mixed")
    base = dict(resolution="1080p", fmt=MAIN_FORMAT)
    # A: main grid (recommended format)
    for d in dists:
        for c in conds:
            for ec in EC_LEVELS:
                add(sweep="A", **base, distance=d, condition=c, ec=ec)
    # B: square sensor
    for d in dists:
        for c in ("clean", "mixed"):
            for ec in ("L", "M"):
                add(sweep="B", resolution="1536sq", fmt=MAIN_FORMAT, distance=d, condition=c,
                    ec=ec)
    # C: payload format / quiet zone (num_qz2 rows come from A)
    for d in dists:
        for fmt in ("num_qz4", "text_qz4", "long_qz4"):
            for c in ("clean", "mixed"):
                add(sweep="C", resolution="1080p", fmt=fmt, distance=d, condition=c, ec="M")
    # D: physical QR size (phone fill vs. bigger display / printed card)
    for d in (1.0, 1.5, 2.0):
        for qr_cm in (6.3, 9.0, 12.0, 16.0, 20.0):
            for c in ("clean", "mixed"):
                add(sweep="D", **base, distance=d, condition=c, ec="M", qr_cm=qr_cm)
    # G: check-in attempt = burst of 8 frames (aide holds the phone ~0.5-1 s)
    for d in dists:
        for c in ("mixed", "lowlight", "motion"):
            add(reps=max(4, n // 2), sweep="G", **base, distance=d, condition=c, ec="M",
                burst=8)
    return tasks


def benchmark(n: int = 40) -> dict:
    """Single-process timing on representative frames (no pool contention)."""
    import cv2

    reader = PresenceReader()
    out = {}
    cases = (("1080p, code found (0.4 m)", "1080p", 0.4),
             ("1080p, code too small (1.0 m) — all fallbacks run", "1080p", 1.0),
             ("1080p, no phone in frame", "1080p", None),
             ("1536², code found (0.4 m)", "1536sq", 0.4))
    for label, res, d in cases:
        times = []
        hits = 0
        for i in range(n):
            payload = _payload(MAIN_FORMAT, i)
            sp = SceneParams(payload=payload, ec="M", distance_m=d or 40.0,
                             qr_size_cm=None if d else 0.5, quiet=2, resolution=res,
                             condition="clean", seed=80_000 + i)
            frame, _ = render(sp)
            reader.read(frame)  # warm caches
            t = time.perf_counter()
            r = reader.read(frame)
            times.append((time.perf_counter() - t) * 1000)
            hits += payload in r.texts
        times.sort()
        out[label] = {"median_ms": statistics.median(times),
                      "p95_ms": times[int(0.95 * (len(times) - 1))],
                      "max_ms": times[-1], "hit_rate": hits / n}
    frame, _ = render(SceneParams(payload=_payload(MAIN_FORMAT, 0), distance_m=0.4, quiet=2,
                                  resolution="1080p", condition="clean", seed=7))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    t = time.perf_counter()
    for _ in range(20):
        reader._decode_multi(reader.qr, gray)
    out["stage1_only_ms"] = (time.perf_counter() - t) * 1000 / 20
    return out


def contact_sheet(path: Path) -> None:
    """Phone crops at each distance (mixed condition), magnified with nearest
    neighbour so you see the real pixels the decoder / a vision model gets."""
    import cv2

    tiles = []
    for d in DISTANCES:
        sp, payload, _ = _scene({"seed": 4242, "fmt": MAIN_FORMAT, "ec": "M",
                                 "resolution": "1080p", "distance": d, "condition": "mixed"})
        frame, meta = render(sp)
        q = np.array(meta["quad"])
        cx, cy = q.mean(axis=0)
        half = 0.12 * focal_px(1920) / d / 2 + 6  # 12 cm window around the phone
        x0, y0 = int(max(0, cx - half)), int(max(0, cy - half * 1.4))
        crop = frame[y0:int(cy + half * 1.4), x0:int(cx + half)]
        tile = cv2.resize(crop, (200, 280), interpolation=cv2.INTER_NEAREST)
        cv2.putText(tile, f"{d} m", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        tiles.append(tile)
    cv2.imwrite(str(path), np.hstack(tiles))


# ----------------------------------------------------------------------------- report


def rate(rows):
    return sum(r["ok"] for r in rows) / len(rows) if rows else float("nan")


def pct(x):
    return "–" if x != x else f"{100 * x:.0f}%"


def write_report(rows: list[dict], bench: dict, n: int, wall_s: float) -> str:
    by = defaultdict(list)
    for r in rows:
        by[r["sweep"]].append(r)
    A, B, C, D, G = by["A"], by["B"], by["C"], by["D"], by["G"]
    dists = sorted({r["distance"] for r in A})
    conds = [c for c in CONDITIONS if any(r["condition"] == c for r in A)]
    f1080, f1536 = focal_px(1920), focal_px(1536)
    num = _payload(MAIN_FORMAT, 0)
    txt = _payload("text_qz4", 0)

    def cell(rows_, **kw):
        return [r for r in rows_ if all(r.get(k) == v for k, v in kw.items())]

    def hdr(first: str, extra_cols: int = 0):
        w(f"| {first} | " + " | ".join(f"{d} m" for d in dists) + " |")
        w("|---|" + "---|" * (len(dists) + extra_cols))

    L: list[str] = []
    w = L.append
    w("# Spike S4 — Can a doorbell camera read a phone QR at ~1 m? (synthetic)\n")
    w("> **This is a synthetic evaluation.** Frames are rendered, not captured. "
      "The lens, blur, compression and lighting models are approximations "
      "(see Assumptions). It shows *where the physics breaks* and how to shape the code; it "
      "does **not** replace validation on real Ring footage — next step: film the Caregiver "
      "Pass at 0.3 / 0.5 / 0.75 / 1.0 m through the actual doorbell (Partner API live view "
      "and snapshots) and rerun `PresenceReader` on those frames.\n")
    w(f"Generated by `eval/presence/run_eval.py` — {sum(r.get('burst', 1) for r in rows)} "
      f"rendered frames ({n} trials per cell), wall time {wall_s:.0f} s. Reader: "
      "`doorledger.presence_reader.PresenceReader` (OpenCV 5 QRCodeDetector + "
      "QRCodeDetectorAruco, CLAHE, crop + upscale + unsharp mask). A trial counts as a "
      "success only if the exact payload is decoded **and** passes MAC verification.\n")

    w("## Assumptions\n")
    w(f"- Ring Partner API video/snapshots are at most 1920×1080; some doorbells are 1536×1536. "
      f"Horizontal FOV 150°. Lens = equidistant fisheye, focal ≈ (W/2)/(FOV/2): "
      f"**{f1080:.0f} px/rad at 1080p**, **{f1536:.0f} px/rad at 1536²**. An object of size "
      f"*s* at distance *d* near the image centre spans ≈ f·s/d px. A rectilinear lens with "
      f"the same FOV would give ~3× fewer pixels, so this is the optimistic case.")
    w("- Phone 7.1×14.7 cm, screen 6.6 cm wide; the QR including its quiet zone fills 95% of "
      "the screen width → **6.3 cm**. The 6-digit fallback sits under it (~1.2 cm digits).")
    w(f"- Payload formats: `num_qz2` (recommended) = 25-digit door-scoped compact code "
      f"`{num}` → QR numeric mode, **version {qr_version(num, 'M')}** at M "
      f"({qr_modules(num, 'M', 2).shape[0]} modules incl. 2-module quiet zone). "
      f"`text_qz4` = `{txt}` → version {qr_version(txt, 'M')} at M "
      f"({qr_modules(txt, 'M', 4).shape[0]} modules incl. 4-module quiet zone). "
      f"`long_qz4` = 24-char visit id + 128-bit MAC (version "
      f"{qr_version(_payload('long_qz4', 0), 'M')}).")
    w("- Every condition keeps a realistic baseline: optical blur σ 0.5–0.8 px, sensor noise, "
      "JPEG q70–85, tilt ±5°, roll ±8°, mild barrel warp, phone ≤6° off-axis. Stress "
      "conditions: `tilt` 10–25° yaw+pitch; `motion` 4–9 px motion blur; `blur` σ 1.0–1.6; "
      "`jpeg_low` q38–47; `lowlight` scene at 15–30% brightness, noise σ 7–14, screen bloom; "
      "`glare` specular blob + raised black level; `barrel` strong distortion, 15–30° "
      "off-axis; `mixed` = random moderate mix of everything (the most realistic row).")
    w("- A *burst* (table G) = 8 frames of one hold: same pose/scene, per-frame hand shake "
      "±3°, motion blur, noise and compression re-drawn. Real frames are more correlated than "
      "this, so burst numbers are an upper bound.\n")
    ppm = {d: f1080 * 0.063 / d / qr_modules(num, "M", 2).shape[0] for d in dists}
    w("Expected pixels per module for the recommended code at 1080p: " + ", ".join(
        f"{d} m → {ppm[d]:.1f}" for d in dists) + ". The OpenCV decoder needs roughly "
      "≥2.5–3 px/module once blur and compression are applied (table E).\n")

    w(f"## A. Per-frame decode rate — 1080p, phone-size QR, `{MAIN_FORMAT}`\n")
    w("Each cell: EC **L / M / Q / H**.\n")
    hdr("condition")
    for c in conds:
        w(f"| {c} | " + " | ".join(" / ".join(pct(rate(cell(A, condition=c, distance=d, ec=ec)))
                                               for ec in EC_LEVELS) for d in dists) + " |")
    w("| **all conditions** | " + " | ".join(
        " / ".join(pct(rate(cell(A, distance=d, ec=ec))) for ec in EC_LEVELS) for d in dists)
      + " |\n")
    w("EC level M only (the recommendation):\n")
    hdr("condition")
    for c in conds:
        w(f"| {c} | " + " | ".join(pct(rate(cell(A, condition=c, distance=d, ec="M")))
                                   for d in dists) + " |")
    w("")

    if G:
        w("## G. Check-in attempt success — burst of 8 frames, EC M\n")
        w("Success = at least one verified decode among the 8 frames.\n")
        hdr("condition")
        for c in ("mixed", "lowlight", "motion"):
            w(f"| {c} | " + " | ".join(pct(rate(cell(G, condition=c, distance=d)))
                                       for d in dists) + " |")
        w("")

    if C:
        w("## C. Payload format and quiet zone (EC M, 1080p)\n")
        hdr("format / condition")
        for fmt in FORMATS:
            for c in ("clean", "mixed"):
                src = A if fmt == MAIN_FORMAT else C
                w(f"| `{fmt}` {c} | " + " | ".join(
                    pct(rate(cell(src, fmt=fmt, condition=c, distance=d, ec="M")))
                    for d in dists) + " |")
        w("\n" + "; ".join(f"`{k}` = {v[0]}" for k, v in FORMATS.items()) + ".\n")

    if B:
        w("## B. Square 1536×1536 sensor (fewer px/rad), `num_qz2`\n")
        hdr("condition (L / M)")
        for c in ("clean", "mixed"):
            w(f"| {c} | " + " | ".join(" / ".join(
                pct(rate(cell(B, condition=c, distance=d, ec=ec))) for ec in ("L", "M"))
                for d in dists) + " |")
        w("")

    if D:
        w("## D. Physical QR size needed at longer range (EC M, `num_qz2`, 1080p)\n")
        sizes = sorted({r["qr_cm"] for r in D})
        w("| distance | condition | " + " | ".join(f"{s:g} cm" for s in sizes) + " |")
        w("|---|---|" + "---|" * len(sizes))
        for d in sorted({r["distance"] for r in D}):
            for c in ("clean", "mixed"):
                w(f"| {d} m | {c} | " + " | ".join(
                    pct(rate(cell(D, distance=d, condition=c, qr_cm=s))) for s in sizes) + " |")
        w("\n6.3 cm = QR filling a phone screen; 9 cm ≈ the largest QR a phone can show; "
          "12–20 cm = tablet or printed badge.\n")

    w("## E. Per-frame decode rate vs pixels per module (all single-frame trials)\n")
    single = [r for r in rows if r.get("burst", 1) == 1]
    bins = [(0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.5), (4.5, 6.0),
            (6.0, 99)]
    w("| px/module | frames | clean / tilt / glare | all conditions |")
    w("|---|---|---|---|")
    for lo, hi in bins:
        rs = [r for r in single if lo <= r["px_per_module"] < hi]
        easy = [r for r in rs if r["condition"] in ("clean", "tilt", "glare")]
        w(f"| {lo:g}–{hi if hi < 99 else '∞'} | {len(rs)} | {pct(rate(easy))} | "
          f"{pct(rate(rs))} |")
    w("")

    w("## F. Timing (Apple Silicon, one process, `PresenceReader.read`, 1 frame)\n")
    w("| case | median | p95 | max | found |")
    w("|---|---|---|---|---|")
    for k, v in bench.items():
        if isinstance(v, dict):
            w(f"| {k} | {v['median_ms']:.1f} ms | {v['p95_ms']:.1f} ms | {v['max_ms']:.1f} ms "
              f"| {pct(v['hit_rate'])} |")
    w(f"\nStage 1 alone (`detectAndDecodeMulti` on the 1080p gray frame): "
      f"{bench['stage1_only_ms']:.1f} ms.")
    stages = defaultdict(int)
    for r in single:
        if r["ok"]:
            stages[r["stage"]] += 1
    w(" Stage that produced the hit (single-frame trials): " + ", ".join(
        f"`{k}` {v}" for k, v in sorted(stages.items(), key=lambda x: -x[1])) + ".")
    fr = sum(r["false_reads"] for r in rows)
    w(f" Non-matching strings returned by OpenCV: {fr} (all would be rejected by the MAC).\n")

    w("## Fallback digits\n")
    dh = {d: f1080 * 0.012 / d for d in dists}
    w("Digit height in the frame for 1.2 cm digits: " + ", ".join(
        f"{d} m → {dh[d]:.0f} px" for d in dists) + ". Not evaluated here (needs a vision "
      "model / OCR); see `contact_sheet.png` for what the camera actually sees at each "
      "distance (mixed condition, magnified with nearest-neighbour).\n")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="trials per cell")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()
    n = 4 if args.quick else args.n
    tasks = build_tasks(n, args.quick)
    print(f"{len(tasks)} trials on {args.workers} workers…", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as ex:
        rows = list(ex.map(run_trial, tasks, chunksize=4))
    wall = time.time() - t0
    print(f"grid done in {wall:.0f} s; benchmarking…", flush=True)
    bench = benchmark(10 if args.quick else 40)
    contact_sheet(HERE / "contact_sheet.png")
    (HERE / "results.json").write_text(json.dumps({"rows": rows, "bench": bench}))
    report = write_report(rows, bench, n, wall)
    notes = HERE / "RESULTS_NOTES.md"
    if notes.exists():  # hand-written interpretation, kept across reruns
        report = report.replace("## Assumptions", notes.read_text().strip() + "\n\n## Assumptions",
                                1)
    (HERE / "RESULTS.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
