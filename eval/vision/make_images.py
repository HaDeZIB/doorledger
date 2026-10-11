"""Generate the synthetic labeled doorbell test set for spike S3.

Generator: Stability AI Stable Image Core on Bedrock (us-west-2). Amazon Nova Canvas was the
first choice but is marked Legacy on this account ("not actively used in the last 30 days")
and refuses calls; Stable Image Core is the cheapest active text-to-image model on Bedrock
(US$0.04/image, AWS Price List 2026-10-08).

Each generated frame is post-processed to look more like a Ring doorbell frame:
  * resized to a Ring-native resolution (1:1 -> 1536x1536 "head-to-toe", 16:9 -> 1920x1080)
  * mild barrel (fisheye) distortion
  * JPEG q=78 re-encode (stream-like compression)
A few frames are additionally turned into "night IR" variants (grayscale, crushed contrast,
sensor noise, vignette) via PIL; these are marked with derived_from in labels.json.

labels.json starts from the intended scene labels below, but ground truth was then corrected
by visually inspecting contact_sheet.png (see LABEL_FIXES).

Usage:
  uv run --no-project --python 3.12 --with boto3 --with pillow --with numpy \
      eval/vision/make_images.py [--skip-generate]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
RAW = HERE / "images" / "raw"
OUT = HERE / "images"
MODEL_ID = "stability.stable-image-core-v1:1"
REGION = "us-west-2"
PRICE_PER_IMAGE = 0.04

STYLE = (
    "Ring video doorbell camera frame, security camera footage, high-angle wide-angle fisheye view "
    "from a doorbell mounted at chest height beside the front door, looking down and out at the "
    "front porch, doormat and doorstep of a suburban house, slight barrel distortion, realistic "
    "photo, slightly soft focus, compressed video still, no text, no timestamp, no overlay"
)
NEG = ("text, letters, watermark, timestamp, logo, caption, overlay, cartoon, illustration, "
       "painting, 3d render, split screen, border")
DUSK = "dusk lighting, low light, warm porch light on"
DAY = "daylight"

F = dict(package_visible=False, person_present=False, person_carrying_package=False,
         vehicle_present=False, phone_screen_shown=False)


def L(**kw):
    d = dict(F)
    d.update(kw)
    return d


# id, class, aspect, scene prompt, intended labels
SCENES = [
    ("empty_01", "empty_porch", "1:1", f"{DAY}, empty concrete porch with a doormat, nobody there", L()),
    ("empty_02", "empty_porch", "1:1", f"{DUSK}, empty wooden porch, front walkway, lawn, nobody there", L()),
    ("empty_03", "empty_porch", "16:9", f"{DAY}, empty front porch steps and front yard with sidewalk, no cars, no people", L()),
    ("box_01", "box_on_mat", "1:1", f"{DAY}, a small brown cardboard shipping box sitting on the doormat, nobody there", L(package_visible=True)),
    ("box_02", "box_on_mat", "1:1", f"{DAY}, a small taped cardboard parcel left on the front doorstep next to the door, nobody there", L(package_visible=True)),
    ("box_03", "box_on_mat", "1:1", f"{DUSK}, one small cardboard box on the doormat, nobody there", L(package_visible=True)),
    ("box_04", "box_on_mat", "16:9", f"{DAY}, a medium cardboard box on the porch floor near the door, front yard visible, nobody there", L(package_visible=True)),
    ("rx_01", "pharmacy_bag", "1:1", f"{DAY}, a white paper pharmacy prescription bag stapled shut resting on the doormat, nobody there", L(package_visible=True)),
    ("rx_02", "pharmacy_bag", "1:1", f"{DAY}, a silver insulated cooler mailer pouch (medication cold-chain shipping bag) lying on the doorstep, nobody there", L(package_visible=True)),
    ("rx_03", "pharmacy_bag", "1:1", f"{DUSK}, a small white styrofoam insulated cooler box for medicine on the porch floor by the door, nobody there", L(package_visible=True)),
    ("rx_04", "pharmacy_bag", "1:1", f"{DAY}, a padded plastic pharmacy mailer envelope on the doormat, nobody there", L(package_visible=True)),
    ("carry_01", "courier_approaching", "1:1", f"{DAY}, a delivery driver in a uniform walking up the front walkway toward the door carrying a cardboard box in both hands", L(person_present=True, person_carrying_package=True)),
    ("carry_02", "courier_approaching", "1:1", f"{DAY}, a courier holding a small parcel approaching the front door on the porch steps", L(person_present=True, person_carrying_package=True)),
    ("carry_03", "courier_approaching", "16:9", f"{DAY}, a delivery man carrying a box walking from the street up the driveway toward the house", L(person_present=True, person_carrying_package=True)),
    ("carry_04", "courier_approaching", "1:1", f"{DUSK}, a delivery worker with a cardboard package under one arm stepping onto the porch", L(person_present=True, person_carrying_package=True)),
    ("place_01", "courier_placing", "1:1", f"{DAY}, a delivery driver bending down placing a cardboard box onto the doormat", L(person_present=True, person_carrying_package=True, package_visible=True)),
    ("place_02", "courier_placing", "1:1", f"{DAY}, a courier crouching and setting a parcel down on the porch floor next to the door", L(person_present=True, person_carrying_package=True, package_visible=True)),
    ("place_03", "courier_placing", "1:1", f"{DUSK}, a delivery person kneeling on the porch putting a small box down on the doorstep", L(person_present=True, person_carrying_package=True, package_visible=True)),
    ("pickup_01", "elder_pickup", "1:1", f"{DAY}, an elderly woman with gray hair bending to pick up a cardboard box from the doormat", L(person_present=True, person_carrying_package=True, package_visible=True)),
    ("pickup_02", "elder_pickup", "1:1", f"{DAY}, an old man in a cardigan standing in the open doorway holding a small parcel he just picked up from the porch", L(person_present=True, person_carrying_package=True)),
    ("pickup_03", "elder_pickup", "1:1", f"{DUSK}, an elderly woman reaching down for a white pharmacy bag on the doorstep", L(person_present=True, person_carrying_package=True, package_visible=True)),
    ("phone_01", "caregiver_phone", "1:1", f"{DAY}, close up, a home caregiver nurse in blue scrubs standing right in front of the doorbell holding a smartphone with its bright screen facing the camera", L(person_present=True, phone_screen_shown=True)),
    ("phone_02", "caregiver_phone", "1:1", f"{DAY}, a woman in teal medical scrubs at the front door holding up her phone screen toward the doorbell camera at close range", L(person_present=True, phone_screen_shown=True)),
    ("phone_03", "caregiver_phone", "1:1", f"{DUSK}, a caregiver in scrubs holding a glowing smartphone screen up to the doorbell camera, very close", L(person_present=True, phone_screen_shown=True)),
    ("phone_04", "caregiver_phone", "1:1", f"{DAY}, a male nurse in navy scrubs on the porch showing a phone screen to the camera with his arm extended", L(person_present=True, phone_screen_shown=True)),
    ("car_01", "vehicle", "16:9", f"{DAY}, a silver sedan parked in the driveway in front of the house, empty porch, nobody there", L(vehicle_present=True)),
    ("car_02", "vehicle", "16:9", f"{DAY}, a white delivery van parked at the curb in front of the house, empty porch, nobody there", L(vehicle_present=True)),
    ("car_03", "vehicle", "1:1", f"{DUSK}, an SUV parked in the driveway seen past the porch railing, nobody there", L(vehicle_present=True)),
    ("away_01", "person_leaving", "1:1", f"{DAY}, a delivery driver seen from behind walking away from the house down the front walkway, empty handed", L(person_present=True)),
    ("away_02", "person_leaving", "16:9", f"{DAY}, a person seen from behind walking away down the driveway toward the street, empty handed", L(person_present=True)),
    ("away_03", "person_leaving", "1:1", f"{DUSK}, a woman seen from behind leaving the porch and walking down the steps, empty handed", L(person_present=True)),
    ("neg_plant", "hard_negative", "1:1", f"{DAY}, a large terracotta potted plant beside the front door on the porch, nobody there, no boxes", L()),
    ("neg_mat", "hard_negative", "1:1", f"{DAY}, a brown coir doormat on the porch, top-down, nobody there, no boxes", L()),
    ("neg_bin", "hard_negative", "1:1", f"{DAY}, a blue recycling bin and a trash can at the side of the porch, nobody there", L()),
    ("neg_shadow", "hard_negative", "1:1", f"{DAY}, harsh afternoon sun casting long rectangular shadows of the porch railing across the empty porch floor, nobody there", L()),
    ("neg_dog", "hard_negative", "1:1", f"{DAY}, a golden retriever dog sitting on the doormat, no people, no boxes", L()),
    # Round 2 (added after label fixes left only 7 package positives): more parcels at rest.
    ("pkg_05", "box_on_mat", "1:1", f"{DAY}, a brown cardboard box sitting on the porch floor right in front of the door, nobody there", L(package_visible=True)),
    ("pkg_06", "box_on_mat", "1:1", f"{DAY}, two cardboard boxes stacked on the doorstep, nobody there", L(package_visible=True)),
    ("pkg_07", "pharmacy_bag", "1:1", f"{DAY}, a yellow padded envelope mailer lying flat on the doormat, nobody there", L(package_visible=True)),
    ("pkg_08", "pharmacy_bag", "1:1", f"{DUSK}, a white plastic poly mailer bag lying on the doorstep, nobody there", L(package_visible=True)),
    ("pkg_09", "box_and_person", "1:1", f"{DAY}, a cardboard box left on the doormat in the foreground, and a delivery driver in the background walking away down the front path", L(package_visible=True, person_present=True)),
    ("pkg_10", "box_on_mat", "16:9", f"{DAY}, a cardboard box on the porch steps, wide view of the front yard and sidewalk, nobody there", L(package_visible=True)),
    ("pkg_11", "pharmacy_bag", "1:1", f"{DUSK}, a silver insulated cooler bag on the porch floor beside a potted plant, nobody there", L(package_visible=True)),
    ("pkg_12", "box_on_mat", "1:1", f"{DAY}, a large cardboard box leaning against the closed front door, nobody there", L(package_visible=True)),
]

# Stable Image Core never rendered a phone with its SCREEN toward the camera (all 4 caregiver
# frames show the back of the phone). Those originals are kept as hard negatives, and a
# "screen shown" positive is composited onto each with PIL: a lit screen showing a 6-digit
# presence code is drawn over the phone. Boxes are in post-processed (Ring-size) pixel coords,
# read off a gridded crop of each frame.
SCREEN_BOXES = {
    "phone_01": (724, 902, 880, 1072),
    "phone_02": (502, 462, 603, 636),
    "phone_03": (732, 1147, 903, 1288),
    "phone_04": (730, 747, 943, 858),
}

# Night-IR variants derived from generated frames (grayscale, noise). Labels inherit from source.
IR_FROM = ["empty_01", "box_01", "rx_02", "carry_01", "phone_01_screen", "neg_dog"]

# Ground-truth corrections after visual inspection of the contact sheet (generated images often
# do not match their prompt). key -> (field overrides, reason, new class or None).
LABEL_FIXES: dict[str, tuple[dict, str, str | None]] = {
    "box_03": ({"package_visible": False}, "no box was generated; only a small round puck on the mat", "empty_porch"),
    "box_04": ({"package_visible": False}, "no box was generated; empty doormat", "empty_porch"),
    "rx_04": ({"package_visible": False}, "no mailer generated; a white camera-like puck on a round mat", "hard_negative"),
    "place_01": ({"package_visible": False}, "box still held above the mat, not resting on the floor", None),
    "place_03": ({"package_visible": False}, "person standing in doorway holding a small box; nothing on the floor", "courier_approaching"),
    "pickup_01": ({"package_visible": False}, "parcel already lifted, held at waist; nothing on the floor", None),
    "pickup_02": ({"person_carrying_package": False}, "elderly man is empty-handed in the doorway", "person_at_door"),
    "pickup_03": ({"package_visible": False}, "elderly woman carrying two white bags; nothing on the floor", None),
    "phone_01": ({"phone_screen_shown": False}, "phone held with its BACK toward the camera", "caregiver_phone_back"),
    "phone_02": ({"phone_screen_shown": False}, "two phones, both with their BACK toward the camera", "caregiver_phone_back"),
    "phone_03": ({"phone_screen_shown": False}, "phone held with its BACK toward the camera", "caregiver_phone_back"),
    "phone_04": ({"phone_screen_shown": False}, "phone held landscape with its BACK toward the camera", "caregiver_phone_back"),
    "away_01": ({}, "actually walking TOWARD the door (back to camera), empty-handed", "person_at_door"),
    "away_03": ({}, "actually walking TOWARD the door at dusk (back to camera)", "person_at_door"),
}
# Fields a careful human could reasonably label either way: not scored for that item.
AMBIGUOUS: dict[str, tuple[list[str], str]] = {
    "rx_03": (["package_visible"], "white cube on porch: insulated cooler box or a small appliance/bin"),
    "away_02": (["person_carrying_package", "vehicle_present"],
                "person carries a dark handbag/duffel (not clearly a parcel); cars parked in a driveway "
                "ACROSS the street (missed in first labeling pass, flagged by the models)"),
    "neg_shadow": (["vehicle_present"], "tiny cars parked far down the street at the top edge; not 'close to the house' "
                   "but visible (missed in first labeling pass, flagged by Nova 2 Lite)"),
    "place_02": (["person_carrying_package"], "courier crouching with hands still on a box that rests on the mat"),
}
EXCLUDE: dict[str, str] = {}


def draw_screen(img: Image.Image, box: tuple[int, int, int, int], code: str) -> Image.Image:
    img = img.copy()
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=12, fill=(18, 18, 20))  # bezel
    inset = max(5, (x1 - x0) // 18)
    sx0, sy0, sx1, sy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    d.rounded_rectangle((sx0, sy0, sx1, sy1), radius=8, fill=(236, 244, 255))
    w, h = sx1 - sx0, sy1 - sy0
    portrait = h >= w
    # header bar + big code + small QR-like block, like a presence-code screen
    d.rectangle((sx0, sy0, sx1, sy0 + h // 8), fill=(62, 131, 89))
    fs = int((w if portrait else h) * (0.26 if portrait else 0.30))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", fs)
    except OSError:
        font = ImageFont.load_default()
    text = code[:3] + "\n" + code[3:] if portrait else code
    d.multiline_text(((sx0 + sx1) // 2, sy0 + h // 8 + (h * 7 // 8) * (0.35 if portrait else 0.45)), text,
                     fill=(20, 20, 30), font=font, anchor="mm", align="center", spacing=2)
    q = int(min(w, h) * 0.32)
    qx, qy = (sx0 + sx1 - q) // 2 if portrait else sx1 - q - 4, sy1 - q - 4
    rng = random.Random(code)
    cell = max(2, q // 9)
    for i in range(9):
        for j in range(9):
            if rng.random() < 0.5 or (i < 3 and j < 3):
                d.rectangle((qx + i * cell, qy + j * cell, qx + (i + 1) * cell - 1, qy + (j + 1) * cell - 1), fill=(0, 0, 0))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def generate_one(client, sid: str, aspect: str, scene: str, seed: int) -> str:
    out = RAW / f"{sid}.jpg"
    if out.exists():
        return f"{sid}: cached"
    body = {"prompt": f"{scene}. {STYLE}", "negative_prompt": NEG, "aspect_ratio": aspect,
            "output_format": "jpeg", "seed": seed}
    import time
    from botocore.exceptions import ClientError
    for attempt in range(8):
        try:
            resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
            break
        except ClientError as e:  # new accounts have a very low images/minute quota
            if e.response["Error"]["Code"] != "ThrottlingException" or attempt == 7:
                return f"{sid}: ERROR {e}"
            time.sleep(15 * (attempt + 1))
    data = json.loads(resp["body"].read())
    if data.get("finish_reasons", [None])[0] not in (None, "SUCCESS"):
        return f"{sid}: FILTERED {data.get('finish_reasons')}"
    out.write_bytes(base64.b64decode(data["images"][0]))
    return f"{sid}: generated"


def barrel(img: Image.Image, k: float = 0.12) -> Image.Image:
    """Mild barrel distortion via inverse mapping (bilinear)."""
    a = np.asarray(img).astype(np.float32)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    nx, ny = (xx - cx) / cx, (yy - cy) / cy
    r2 = nx * nx + ny * ny
    # Sample source points further out than the destination -> bulging center. Normalised so
    # the corners (r2 = 2) map onto the corners: no out-of-frame sampling / edge smearing.
    scale = (1 + k * r2) / (1 + 2 * k)
    sx = np.clip(nx * scale * cx + cx, 0, w - 1)
    sy = np.clip(ny * scale * cy + cy, 0, h - 1)
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    x1, y1 = np.clip(x0 + 1, 0, w - 1), np.clip(y0 + 1, 0, h - 1)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    top = a[y0, x0] * (1 - fx) + a[y0, x1] * fx
    bot = a[y1, x0] * (1 - fx) + a[y1, x1] * fx
    return Image.fromarray(np.clip(top * (1 - fy) + bot * fy, 0, 255).astype(np.uint8))


def ringify(raw: Image.Image, aspect: str) -> Image.Image:
    size = (1536, 1536) if aspect == "1:1" else (1920, 1080)
    img = raw.convert("RGB").resize(size, Image.LANCZOS)
    return barrel(img)


def night_ir(img: Image.Image, seed: int) -> Image.Image:
    g = np.asarray(img.convert("L")).astype(np.float32)
    g = np.clip((g - 40) * 1.25, 0, 255)  # crush blacks, IR-ish flat contrast
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    g = g * np.clip(1.15 - 0.45 * r ** 2, 0.35, 1.0)  # IR illuminator falloff
    rng = np.random.default_rng(seed)
    g = np.clip(g + rng.normal(0, 9, g.shape), 0, 255)
    return Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)).convert("RGB")


def save_jpeg(img: Image.Image, path: Path) -> None:
    img.save(path, "JPEG", quality=78)


def contact_sheet(items: list[dict], path: Path, cols: int = 7, tile: int = 300) -> None:
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile, rows * (tile + 22)), "white")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, it in enumerate(items):
        im = Image.open(OUT / it["file"])
        im.thumbnail((tile, tile))
        x, y = (i % cols) * tile, (i // cols) * (tile + 22)
        sheet.paste(im, (x + (tile - im.width) // 2, y + 22 + (tile - im.height) // 2))
        d.text((x + 4, y + 3), it["id"], fill="black", font=font)
    sheet.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-generate", action="store_true", help="only post-process cached raws")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    if not args.skip_generate:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=REGION)
        todo = [s for s in SCENES if not (RAW / f"{s[0]}.jpg").exists()]
        print(f"generating {len(todo)} images, est. ${len(todo) * PRICE_PER_IMAGE:.2f}")
        with ThreadPoolExecutor(1) as ex:
            futs = [ex.submit(generate_one, client, sid, asp, scene, 1000 + i)
                    for i, (sid, _c, asp, scene, _l) in enumerate(SCENES)]
            for f in futs:
                print(" ", f.result())

    labels = []
    by_id = {}
    for sid, cls, aspect, scene, lab in SCENES:
        raw = RAW / f"{sid}.jpg"
        if not raw.exists():
            print(f"missing raw for {sid}, skipping", file=sys.stderr)
            continue
        img = ringify(Image.open(raw), aspect)
        save_jpeg(img, OUT / f"{sid}.jpg")
        by_id[sid] = img
        labels.append({"id": sid, "file": f"{sid}.jpg", "class": cls, "lighting":
                       "dusk" if DUSK in scene else "day", "prompt": scene, "labels": dict(lab)})
    for i, (src, box) in enumerate(SCREEN_BOXES.items()):
        if src not in by_id:
            continue
        sid = f"{src}_screen"
        img = draw_screen(by_id[src], box, f"{482917 + 1111 * i:06d}")
        save_jpeg(img, OUT / f"{sid}.jpg")
        by_id[sid] = img
        base = next(x for x in labels if x["id"] == src)
        lab = dict(base["labels"], phone_screen_shown=True)
        labels.append({"id": sid, "file": f"{sid}.jpg", "class": "caregiver_phone_screen", "lighting": base["lighting"],
                       "prompt": base["prompt"] + " [PIL composite: lit phone screen with presence code]",
                       "derived_from": src, "composite": True, "labels": lab})
    for i, src in enumerate(IR_FROM):
        if src not in by_id:
            continue
        sid = f"{src}_ir"
        save_jpeg(night_ir(by_id[src], 7 + i), OUT / f"{sid}.jpg")
        base = next(x for x in labels if x["id"] == src)
        labels.append({"id": sid, "file": f"{sid}.jpg", "class": base["class"], "lighting": "night_ir",
                       "prompt": base["prompt"], "derived_from": src, "composite": base.get("composite", False),
                       "labels": dict(base["labels"])})

    # Apply visual-inspection corrections. Fixes on a source propagate to IR variants (chain of
    # derived_from), but never override the phone_screen_shown=True of a composited screen.
    ids = {x["id"]: x for x in labels}
    for it in labels:
        chain, cur = [], it
        while cur:
            chain.append(cur["id"])
            cur = ids.get(cur.get("derived_from") or "")
        for key in reversed(chain):
            if key in LABEL_FIXES:
                over, why, new_cls = LABEL_FIXES[key]
                if it.get("composite"):
                    over = {k: v for k, v in over.items() if k != "phone_screen_shown"}
                    new_cls = None
                it["labels"].update(over)
                it.setdefault("fix_notes", []).append(why)
                if new_cls:
                    it["class"] = new_cls
            if key in AMBIGUOUS:
                it["ambiguous"], why = AMBIGUOUS[key]
                it.setdefault("fix_notes", []).append("ambiguous: " + why)
        src_ex = EXCLUDE.get(it["id"]) or EXCLUDE.get(it.get("derived_from") or "")
        if src_ex:
            it["excluded"] = src_ex
    (HERE / "labels.json").write_text(json.dumps(labels, indent=2))
    contact_sheet(labels, HERE / "contact_sheet.png")
    n = sum(1 for x in labels if not x.get("excluded"))
    print(f"wrote {len(labels)} items ({n} usable) -> labels.json, contact_sheet.png")
    return 0


if __name__ == "__main__":
    random.seed(0)
    sys.exit(main())
