"""Synthetic doorbell frames with a phone showing a DoorLedger presence QR.

Spike S4: can a doorbell-style camera read a QR shown on a phone at ~1 m?

Geometry assumptions (state them, they drive everything):

* Ring doorbells stream at most 1920x1080 through the Partner API (some models
  are 1536x1536 "head-to-toe"); horizontal FOV ~150-155 deg.
* Lens modelled as an equidistant fisheye, r = f * theta, so the focal length in
  pixels is f = (W/2) / (HFOV/2):  1920 px @ 150 deg -> f ~= 733 px/rad,
  1536 px @ 150 deg -> f ~= 587 px/rad.  Near the optical axis a small object
  of size s at distance d spans ~ f * s / d pixels.  A rectilinear lens with
  the same FOV would be ~3x *worse* at the centre (f = 960 / tan 75deg = 257),
  so this is the optimistic end for a wide doorbell lens.
* The phone is near the optical axis (aide stands in front of the door, phone
  at chest height); extra off-axis compression is applied with a centre-
  preserving barrel warp.
* Phone: body 7.1 x 14.7 cm, screen 6.6 x 14.3 cm (6.1" class).  The QR
  (including its rendered quiet zone, 4 or 2 modules) fills ``fill`` x screen width (default
  0.95 -> 6.3 cm).  For the size sweep the "phone" is scaled into a card /
  tablet of the requested QR size.

So at 1.0 m, 1080p: a 6.3 cm QR spans ~46 px.  A version-2 symbol (25 modules
+ 8 quiet) then gets ~1.4 px/module -- below what any decoder needs (~2.5-3).
The eval measures where it actually breaks.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import segno

# ----------------------------------------------------------------------------- params

RESOLUTIONS = {"1080p": (1920, 1080), "1536sq": (1536, 1536)}
HFOV_DEG = 150.0
DISTANCES = (0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.5, 2.0)
EC_LEVELS = ("L", "M", "Q", "H")
CONDITIONS = ("clean", "tilt", "motion", "blur", "jpeg_low", "lowlight", "glare", "barrel", "mixed")

PHONE_BODY_CM = (7.1, 14.7)
PHONE_SCREEN_CM = (6.6, 14.3)


def focal_px(width: int, hfov_deg: float = HFOV_DEG) -> float:
    return (width / 2.0) / math.radians(hfov_deg / 2.0)


@dataclass
class SceneParams:
    payload: str
    digits: str = "482913"
    ec: str = "M"
    resolution: str = "1080p"
    distance_m: float = 1.0
    qr_size_cm: float | None = None  # None -> fill * phone screen width
    fill: float = 0.95
    quiet: int = 4  # rendered quiet-zone modules (the white screen continues beyond it)
    condition: str = "clean"
    seed: int = 0
    # Burst mode: same scene/pose/condition (from ``seed``) but per-frame jitter
    # (hand shake +-3 deg, motion blur, sensor noise, compression) from this seed.
    jitter_seed: int | None = None
    # realised random values (filled in by render)
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- QR texture


@lru_cache(maxsize=256)
def qr_modules(payload: str, ec: str, quiet: int = 4) -> np.ndarray:
    """QR matrix (1 = dark) including a ``quiet``-module quiet zone; segno picks the
    smallest version and alphanumeric mode automatically."""
    q = segno.make(payload, error=ec.lower(), micro=False, boost_error=False)
    m = np.array(q.matrix, dtype=np.uint8)
    return np.pad(m, quiet)


def qr_version(payload: str, ec: str) -> int:
    return segno.make(payload, error=ec.lower(), micro=False, boost_error=False).version


def phone_texture(payload: str, ec: str, digits: str, qr_cm: float, fill: float,
                  rng: np.random.Generator, black_level: int, quiet: int = 4) -> tuple[np.ndarray, float, float]:
    """Return (BGR texture, object width cm, object height cm)."""
    screen_w_cm = qr_cm / fill
    scale = screen_w_cm / PHONE_SCREEN_CM[0]
    body_w, body_h = PHONE_BODY_CM[0] * scale, PHONE_BODY_CM[1] * scale
    ppcm = 40.0  # texture resolution, pixels per cm
    W, H = int(round(body_w * ppcm)), int(round(body_h * ppcm))
    tex = np.zeros((H, W, 3), np.uint8)
    tex[:] = (25, 25, 28)  # bezel / case
    bx = int(round((body_w - screen_w_cm) / 2 * ppcm))
    by = int(round((body_h - PHONE_SCREEN_CM[1] * scale) / 2 * ppcm))
    white = int(rng.integers(238, 256))
    tex[by:H - by, bx:W - bx] = (white, white, white)

    mods = qr_modules(payload, ec, quiet)
    n = mods.shape[0]
    qr_px = int(round(qr_cm * ppcm))
    big = np.where(mods == 1, black_level, white).astype(np.uint8)
    big = cv2.resize(big, (n * 16, n * 16), interpolation=cv2.INTER_NEAREST)
    qr_img = cv2.resize(big, (qr_px, qr_px), interpolation=cv2.INTER_AREA)
    qx = (W - qr_px) // 2
    qy = by + int(round(1.6 * scale * ppcm))
    tex[qy:qy + qr_px, qx:qx + qr_px] = qr_img[..., None]

    # 6-digit fallback below the QR (~1.2 cm tall digits on a phone)
    font_scale = 1.2 * scale * ppcm / 22.0
    thickness = max(2, int(round(font_scale * 2.2)))
    (tw, th), _ = cv2.getTextSize(digits, cv2.FONT_HERSHEY_DUPLEX, font_scale, thickness)
    ty = qy + qr_px + int(0.6 * scale * ppcm) + th
    if ty < H - by:
        cv2.putText(tex, digits, ((W - tw) // 2, ty), cv2.FONT_HERSHEY_DUPLEX, font_scale,
                    (black_level,) * 3, thickness, cv2.LINE_AA)
    return tex, body_w, body_h


# ----------------------------------------------------------------------------- background


def porch_background(w: int, h: int, rng: np.random.Generator, dark: float = 1.0) -> np.ndarray:
    img = np.zeros((h, w, 3), np.float32)
    wall = rng.uniform(120, 200, 3)
    grad = np.linspace(1.1, 0.8, h, dtype=np.float32)[:, None, None]
    img[:] = wall * grad
    # door
    dw, dh = int(w * rng.uniform(0.25, 0.4)), int(h * rng.uniform(0.7, 0.9))
    dx = int(w * rng.uniform(0.2, 0.5))
    img[h - dh:, dx:dx + dw] = rng.uniform(40, 110, 3)
    # floor
    img[int(h * 0.85):] = rng.uniform(60, 140, 3)
    # clutter rectangles (plants, mats, windows)
    for _ in range(int(rng.integers(4, 10))):
        rw, rh = int(rng.integers(w // 30, w // 6)), int(rng.integers(h // 30, h // 5))
        rx, ry = int(rng.integers(0, w - rw)), int(rng.integers(0, h - rh))
        img[ry:ry + rh, rx:rx + rw] = rng.uniform(0, 255, 3)
    # person (torso + head) roughly centred - phone is held in front of it
    tx = int(w * rng.uniform(0.42, 0.58))
    tw_, th_ = int(w * 0.22), int(h * 0.6)
    cv2.rectangle(img, (tx - tw_ // 2, int(h * 0.38)), (tx + tw_ // 2, int(h * 0.38) + th_),
                  tuple(float(v) for v in rng.uniform(20, 160, 3)), -1)
    cv2.circle(img, (tx, int(h * 0.27)), int(h * 0.09),
               tuple(float(v) for v in rng.uniform(60, 200, 3)), -1)
    noise = rng.normal(0, 6, (h // 8, w // 8, 3)).astype(np.float32)
    img += cv2.resize(noise, (w, h), interpolation=cv2.INTER_LINEAR)
    img *= dark
    return np.clip(img, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- camera effects


@lru_cache(maxsize=8)
def barrel_maps(w: int, h: int, k: float) -> tuple[np.ndarray, np.ndarray]:
    """Centre-preserving barrel distortion maps (dst -> src)."""
    cx, cy = w / 2.0, h / 2.0
    norm = max(cx, cy)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = (xs - cx) / norm, (ys - cy) / norm
    r2 = dx * dx + dy * dy
    f = 1.0 + k * r2
    return (cx + dx * f * norm).astype(np.float32), (cy + dy * f * norm).astype(np.float32)


def motion_kernel(length: int, angle_deg: float) -> np.ndarray:
    length = max(1, int(length))
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle_deg, 1.0)
    k = cv2.warpAffine(k, rot, (length, length))
    return k / max(k.sum(), 1e-6)


def condition_knobs(cond: str, rng: np.random.Generator) -> dict:
    """Random camera/scene knobs for a named condition.  Every condition keeps
    a realistic baseline (some optical blur + video-grade compression)."""
    k = dict(yaw=rng.uniform(-5, 5), pitch=rng.uniform(-5, 5), roll=rng.uniform(-8, 8),
             optical_sigma=rng.uniform(0.5, 0.8), motion_len=0, motion_angle=0.0,
             jpeg_q=int(rng.integers(70, 86)), noise_sigma=rng.uniform(1.0, 2.5), dark=1.0,
             black_level=int(rng.integers(15, 40)), glare=False, bloom=0.0,
             barrel_k=0.12, off_axis_deg=rng.uniform(0, 6))
    if cond == "tilt":
        k.update(yaw=rng.choice([-1, 1]) * rng.uniform(10, 25),
                 pitch=rng.choice([-1, 1]) * rng.uniform(10, 25))
    elif cond == "motion":
        k.update(motion_len=int(rng.integers(4, 10)), motion_angle=rng.uniform(0, 180))
    elif cond == "blur":
        k.update(optical_sigma=rng.uniform(1.0, 1.6))
    elif cond == "jpeg_low":
        k.update(jpeg_q=int(rng.integers(38, 48)))
    elif cond == "lowlight":
        k.update(dark=rng.uniform(0.15, 0.3), noise_sigma=rng.uniform(7, 14),
                 bloom=rng.uniform(0.25, 0.5), jpeg_q=int(rng.integers(55, 75)))
    elif cond == "glare":
        k.update(glare=True, black_level=int(rng.integers(40, 80)))
    elif cond == "barrel":
        k.update(barrel_k=rng.uniform(0.3, 0.45), off_axis_deg=rng.uniform(15, 30))
    elif cond == "mixed":
        k.update(yaw=rng.uniform(-20, 20), pitch=rng.uniform(-20, 20),
                 optical_sigma=rng.uniform(0.6, 1.1),
                 motion_len=int(rng.integers(0, 6)), motion_angle=rng.uniform(0, 180),
                 jpeg_q=int(rng.integers(50, 76)), noise_sigma=rng.uniform(2, 6),
                 dark=rng.uniform(0.5, 1.0), black_level=int(rng.integers(20, 60)),
                 glare=bool(rng.random() < 0.3), bloom=rng.uniform(0.0, 0.2),
                 barrel_k=rng.uniform(0.12, 0.3), off_axis_deg=rng.uniform(0, 15))
    elif cond != "clean":
        raise ValueError(cond)
    return k


def _project_quad(obj_w_m: float, obj_h_m: float, d: float, f: float, yaw: float, pitch: float,
                  roll: float, center_px: tuple[float, float]) -> np.ndarray:
    hw, hh = obj_w_m / 2, obj_h_m / 2
    pts = np.array([[-hw, -hh, 0], [hw, -hh, 0], [hw, hh, 0], [-hw, hh, 0]], np.float64)
    y, p, r = map(math.radians, (yaw, pitch, roll))
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    P = pts @ (Rz @ Rx @ Ry).T
    Z = d + P[:, 2]
    u = center_px[0] + f * P[:, 0] / Z
    v = center_px[1] + f * P[:, 1] / Z
    return np.stack([u, v], axis=1).astype(np.float32)


def render(sp: SceneParams) -> tuple[np.ndarray, dict]:
    """Render one BGR frame (after JPEG round-trip) and its metadata."""
    rng = np.random.default_rng(sp.seed)
    W, H = RESOLUTIONS[sp.resolution]
    f = focal_px(W)
    kn = condition_knobs(sp.condition, rng)
    if sp.jitter_seed is not None:
        jr = np.random.default_rng(sp.jitter_seed)
        kn["yaw"] += jr.uniform(-3, 3)
        kn["pitch"] += jr.uniform(-3, 3)
        kn["roll"] += jr.uniform(-2, 2)
        kn["motion_len"] = max(0, kn["motion_len"] + int(jr.integers(-2, 3)))
        kn["motion_angle"] = jr.uniform(0, 180)
        kn["jpeg_q"] = int(np.clip(kn["jpeg_q"] + jr.integers(-8, 9), 30, 95))

    qr_cm = sp.qr_size_cm if sp.qr_size_cm is not None else sp.fill * PHONE_SCREEN_CM[0]
    tex, obj_w_cm, obj_h_cm = phone_texture(sp.payload, sp.ec, sp.digits, qr_cm, sp.fill, rng,
                                            kn["black_level"], sp.quiet)

    frame = porch_background(W, H, rng, dark=kn["dark"]).astype(np.float32)

    # phone position: near the optical axis, chest height (slightly below centre)
    ang = math.radians(kn["off_axis_deg"])
    phi = rng.uniform(0, 2 * math.pi)
    cx = W / 2 + f * ang * math.cos(phi)
    cy = H / 2 + f * ang * abs(math.sin(phi)) * 0.6 + H * 0.05
    quad = _project_quad(obj_w_cm / 100, obj_h_cm / 100, sp.distance_m, f,
                         kn["yaw"], kn["pitch"], kn["roll"], (cx, cy))

    # pre-shrink the texture to ~2x the target size, then perspective warp
    target_w = max(4.0, float(np.linalg.norm(quad[1] - quad[0])))
    s = min(1.0, 2.0 * target_w / tex.shape[1])
    if s < 1.0:
        tex = cv2.resize(tex, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    th, tw = tex.shape[:2]
    src = np.array([[0, 0], [tw, 0], [tw, th], [0, th]], np.float32)
    M = cv2.getPerspectiveTransform(src, quad)
    warped = cv2.warpPerspective(tex, M, (W, H), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.ones((th, tw), np.float32), M, (W, H), flags=cv2.INTER_LINEAR)

    # screen emits light: in dark scenes it stays bright (camera exposes for the scene)
    screen = warped.astype(np.float32)
    if kn["dark"] < 1.0:
        screen *= min(1.0, 0.55 + kn["dark"])
    frame = frame * (1 - mask[..., None]) + screen * mask[..., None]

    if kn["glare"]:
        g = np.zeros((H, W), np.float32)
        qc = quad.mean(axis=0) + rng.uniform(-0.25, 0.25, 2) * target_w
        ax = max(2, int(target_w * rng.uniform(0.2, 0.45)))
        cv2.ellipse(g, (int(qc[0]), int(qc[1])), (ax, max(2, int(ax * rng.uniform(0.3, 0.7)))),
                    rng.uniform(0, 180), 0, 360, 1.0, -1)
        g = cv2.GaussianBlur(g, (0, 0), max(1.0, ax * 0.35))
        frame += g[..., None] * rng.uniform(120, 200)

    if kn["bloom"] > 0:
        hi = np.clip(frame - 200, 0, None)
        frame += cv2.GaussianBlur(hi, (0, 0), max(1.0, target_w * 0.02)) * kn["bloom"] * 3

    frame = np.clip(frame, 0, 255).astype(np.uint8)
    if kn["barrel_k"] > 0:
        mx, my = barrel_maps(W, H, round(kn["barrel_k"], 2))
        frame = cv2.remap(frame, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if kn["optical_sigma"] > 0:
        frame = cv2.GaussianBlur(frame, (0, 0), kn["optical_sigma"])
    if kn["motion_len"] > 1:
        frame = cv2.filter2D(frame, -1, motion_kernel(kn["motion_len"], kn["motion_angle"]))
    if kn["noise_sigma"] > 0:
        nrng = rng if sp.jitter_seed is None else np.random.default_rng(sp.jitter_seed + 7)
        frame = np.clip(frame.astype(np.float32) + nrng.normal(0, kn["noise_sigma"], frame.shape),
                        0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, kn["jpeg_q"]])
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)

    n_mod = qr_modules(sp.payload, sp.ec, sp.quiet).shape[0]  # incl. quiet zone
    qr_px = f * (qr_cm / 100) / sp.distance_m
    digit_px = f * (0.012 * qr_cm / (sp.fill * PHONE_SCREEN_CM[0])) / sp.distance_m
    meta = dict(asdict(sp), knobs={k: (float(v) if isinstance(v, (np.floating, float)) else v)
                                   for k, v in kn.items()},
                qr_version=qr_version(sp.payload, sp.ec), qr_cm=qr_cm, focal_px=f,
                qr_px=qr_px, px_per_module=qr_px / n_mod, digit_height_px=digit_px,
                quad=quad.tolist())
    return frame, meta


# ----------------------------------------------------------------------------- CLI


def _demo_payload(compact: bool = True) -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "src"))
    from doorledger.presence import make_code

    secret = bytes(range(32))
    if compact:
        return make_code("V7K2QX", secret, "in", at=1_760_200_000.0)
    return make_code("CLIENT-0042-VISIT-20261011", secret, "in",
                     at=1_760_200_000.0, mac_bytes=16)


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).parent / "samples"))
    ap.add_argument("--per-cell", type=int, default=1)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = _demo_payload()
    index = []
    i = 0
    for res in RESOLUTIONS:
        for d in DISTANCES:
            for cond in CONDITIONS:
                for rep in range(args.per_cell):
                    sp = SceneParams(payload=payload, ec="M", resolution=res, distance_m=d,
                                     condition=cond, seed=1000 + i)
                    frame, meta = render(sp)
                    name = f"{res}_{d:.2f}m_{cond}_{rep}.jpg"
                    cv2.imwrite(str(out / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    meta["file"] = name
                    index.append(meta)
                    i += 1
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"wrote {len(index)} frames to {out}")


if __name__ == "__main__":
    main()
