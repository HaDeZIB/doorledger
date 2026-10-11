"""Spike S3: evaluate Bedrock vision models on the synthetic doorbell set (eval/vision/labels.json).

Uses the exact PROMPT and the same JSON-extraction regex as core/src/doorledger/vision.py
(read from source, so results transfer), via the Converse API.

  uv run --no-project --python 3.12 --with boto3 --with pillow eval/vision/run_eval.py --probe
  uv run --no-project --python 3.12 --with boto3 --with pillow eval/vision/run_eval.py --runs nova-lite,haiku-4.5
  uv run --no-project --python 3.12 --with boto3 --with pillow eval/vision/run_eval.py --report

Raw per-image results accumulate in results_raw.json (completed runs are skipped on re-run).
A hard spend cap (--budget, default US$1.30 for this script) is enforced from the recorded
token usage of all runs so far, using the prices below.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW_PATH = HERE / "results_raw.json"
FIELDS = ["package_visible", "person_present", "person_carrying_package", "vehicle_present",
          "phone_screen_shown"]
REGION = "us-east-1"


def core_prompt() -> str:
    src = (ROOT / "core/src/doorledger/vision.py").read_text()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "PROMPT":
            return ast.literal_eval(node.value)
    raise SystemExit("PROMPT not found in vision.py")


PROMPT_BASE = core_prompt()

# One improved variant (step 4). Same JSON contract, sharper definitions for the fields that
# failed on the base prompt (see RESULTS.md).
PROMPT_V2 = """You are the perception module of a home-care verification system watching a front-door camera.
Describe ONLY what is visible in the image. Answer with a single JSON object and nothing else:
{
  "package_visible": bool,          // a parcel/box/bag/envelope/cooler RESTING on the floor, mat or step. false if every parcel is in someone's hands
  "person_present": bool,           // any person visible near the door, including partly visible or seen from behind
  "person_carrying_package": bool,  // a person is holding a parcel/box/delivery bag in their hands or arms (not a purse or backpack)
  "vehicle_present": bool,          // a car/van/truck visible in the driveway or street close to the house
  "phone_screen_shown": bool,       // the lit DISPLAY of a phone faces the camera (you can see the screen content). false if you only see the back/camera side of a phone
  "confidence": number,             // 0..1, your overall confidence
  "note": string                    // <= 12 words, plain description
}
Doorbell cameras are wide-angle: objects near the edges look stretched. Small devices, pucks or doormats are not parcels."""

PROMPTS = {"base": PROMPT_BASE, "v2": PROMPT_V2}

# Prices: AWS Price List bulk API (offers/v1.0/aws/AmazonBedrock + AmazonBedrockFoundationModels,
# us-east-1, published 2026-10-08/10). "us." inference profiles bill at the regional/geo
# CRIS rate, which for Claude/Nova 2 is ~10% above the "global." rate.
PRICES = {  # USD per 1M tokens (input, output)
    "us.amazon.nova-lite-v1:0": (0.06, 0.24),
    "us.amazon.nova-pro-v1:0": (0.80, 3.20),
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
    "us.anthropic.claude-haiku-5-5": (0.11, 0.55),
    "us.anthropic.claude-sonnet-5-5": (2.20, 11.00),
    "us.anthropic.claude-sonnet-4-6": (3.30, 16.50),
}

T0 = {"temperature": 0}
RUNS = {
    # name: (model_id, inferenceConfig extras, additionalModelRequestFields, max_long_side, prompt)
    "nova-lite": ("us.amazon.nova-lite-v1:0", T0, None, None, "base"),
    "nova-pro": ("us.amazon.nova-pro-v1:0", T0, None, None, "base"),
    "nova-2-lite": ("us.amazon.nova-2-lite-v1:0", T0, None, None, "base"),
    "haiku-4.5": ("us.anthropic.claude-haiku-4-5-20251001-v1:0", T0, None, None, "base"),
    # Haiku 5.5 / Sonnet 5.5 reject non-default temperature (400) and think by default.
    "haiku-5.5": ("us.anthropic.claude-haiku-5-5", {}, {"thinking": {"type": "disabled"}}, None, "base"),
    "sonnet-5.5": ("us.anthropic.claude-sonnet-5-5", {}, {"thinking": {"type": "between_tools"}}, None, "base"),
    # Sonnet 4.6: thinking off unless requested, temperature allowed.
    "sonnet-4.6": ("us.anthropic.claude-sonnet-4-6", T0, None, None, "base"),
}
# Access status on account <account-id> (2026-10-11):
#   haiku-4.5  -> ResourceNotFound "Model use case details have not been submitted" (Anthropic
#                 use-case form in the Bedrock console, one-time per account)
#   haiku-5.5, sonnet-5.5 -> AccessDenied "not available for this account" (us. and global.)


def add_variants() -> None:
    for base in list(RUNS):
        mid, inf, extra, _side, _p = RUNS[base]
        RUNS[f"{base}@768"] = (mid, inf, extra, 768, "base")
        RUNS[f"{base}+v2"] = (mid, inf, extra, None, "v2")
        RUNS[f"{base}@768+v2"] = (mid, inf, extra, 768, "v2")


add_variants()
RUNS["nova-2-lite#rep2"] = RUNS["nova-2-lite"]  # repeat run: temperature-0 determinism check
RUNS["nova-lite#rep2"] = RUNS["nova-lite"]


def parse(text: str) -> dict:
    """Same extraction as doorledger.vision._parse."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"model did not return JSON: {text[:200]!r}")
    return json.loads(match.group(0))


def load_image(path: Path, max_side: int | None) -> tuple[bytes, tuple[int, int]]:
    from PIL import Image
    if max_side is None:
        data = path.read_bytes()
        with Image.open(io.BytesIO(data)) as im:
            return data, im.size
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue(), im.size


def cost_of(rec: dict) -> float:
    pin, pout = PRICES[rec["model_id"]]
    return (rec.get("input_tokens", 0) * pin + rec.get("output_tokens", 0) * pout) / 1e6


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data = json.loads(RAW_PATH.read_text()) if RAW_PATH.exists() else {}

    def spent(self) -> float:
        return sum(cost_of(r) for run in self.data.values() for r in run.get("items", []))

    def save(self) -> None:
        with self.lock:
            RAW_PATH.write_text(json.dumps(self.data, indent=1))


def call(client, model_id, inf, extra, prompt, img: bytes):
    kwargs = dict(modelId=model_id, messages=[{"role": "user", "content": [
        {"image": {"format": "jpeg", "source": {"bytes": img}}}, {"text": prompt}]}],
        inferenceConfig={"maxTokens": 300, **inf})
    if extra:
        kwargs["additionalModelRequestFields"] = extra
    for attempt in range(6):
        t = time.perf_counter()
        try:
            resp = client.converse(**kwargs)
            return resp, (time.perf_counter() - t) * 1000
        except client.exceptions.ThrottlingException:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("throttled 6x")


def run_one(store: Store, client, name: str, items: list[dict], budget: float, limit: int | None = None):
    model_id, inf, extra, side, pkey = RUNS[name]
    prompt = PROMPTS[pkey]
    prev = {r["id"]: r for r in store.data.get(name, {}).get("items", []) if "pred" in r or "parse_error" in r}
    out = []
    for it in items[:limit] if limit else items:
        if it["id"] in prev:  # resume: keep completed items, retry API failures only
            out.append(prev[it["id"]])
            continue
        if store.spent() > budget:
            print(f"[{name}] BUDGET CAP ${budget:.2f} reached, stopping", flush=True)
            break
        img, size = load_image(HERE / "images" / it["file"], side)
        rec = {"id": it["id"], "model_id": model_id, "size": size}
        try:
            resp, ms = call(client, model_id, inf, extra, prompt, img)
            u = resp.get("usage", {})
            text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"] if "text" in c)
            rec.update(latency_ms=round(ms, 1), input_tokens=u.get("inputTokens", 0),
                       output_tokens=u.get("outputTokens", 0), stop=resp.get("stopReason"), text=text)
            try:
                rec["pred"] = parse(text)
            except Exception as e:  # noqa: BLE001
                rec["parse_error"] = str(e)[:200]
        except Exception as e:  # noqa: BLE001
            rec["api_error"] = str(e)[:300]
        out.append(rec)
        with store.lock:
            store.data.setdefault(name, {"model_id": model_id, "max_side": side, "prompt": pkey, "items": []})
            store.data[name]["items"] = out
    store.save()
    n_ok = sum(1 for r in out if "pred" in r)
    run_cost = sum(cost_of(r) for r in out)
    print(f"[{name}] done {n_ok}/{len(out)} ok, run ${run_cost:.4f}, total spent ${store.spent():.4f}", flush=True)


# ---------------------------------------------------------------- metrics
def metrics(run: dict, labels: dict) -> dict:
    items = [r for r in run["items"] if r["id"] in labels]
    n = len(items)
    ok = [r for r in items if "pred" in r]
    res = {"n": n, "parse_fail": sum(1 for r in items if "parse_error" in r),
           "api_fail": sum(1 for r in items if "api_error" in r)}
    for f in FIELDS:
        tp = fp = fn = tn = 0
        for r in items:
            lab = labels[r["id"]]
            if f in lab.get("ambiguous", []):
                continue
            truth = bool(lab["labels"][f])
            # a failed call/parse counts as "False" (what production's label_from_json would do
            # is crash; we score it as a miss so failures hurt recall)
            pred = bool(r.get("pred", {}).get(f)) if "pred" in r else False
            tp += truth and pred
            fp += (not truth) and pred
            fn += truth and (not pred)
            tn += (not truth) and (not pred)
        tot = tp + fp + fn + tn
        res[f] = {"acc": (tp + tn) / tot if tot else None,
                  "prec": tp / (tp + fp) if tp + fp else None,
                  "rec": tp / (tp + fn) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    lat = sorted(r["latency_ms"] for r in ok)
    if lat:
        res["lat_p50"] = statistics.median(lat)
        res["lat_p95"] = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
    tin = [r["input_tokens"] for r in ok]
    tout = [r["output_tokens"] for r in ok]
    if tin:
        res["in_tok"] = statistics.mean(tin)
        res["out_tok"] = statistics.mean(tout)
        pin, pout = PRICES[run["model_id"]]
        res["usd_per_1k"] = (res["in_tok"] * pin + res["out_tok"] * pout) / 1e6 * 1000
    res["mean_acc"] = statistics.mean(res[f]["acc"] for f in FIELDS)
    res["errors"] = [
        {"id": r["id"], "wrong": [f for f in FIELDS if f not in labels[r["id"]].get("ambiguous", [])
                                  and "pred" in r and bool(r["pred"].get(f)) != labels[r["id"]]["labels"][f]],
         "note": r.get("pred", {}).get("note")}
        for r in items]
    res["errors"] = [e for e in res["errors"] if e["wrong"]]
    return res


def pct(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def report(store: Store, labels: dict) -> None:
    rows = {name: metrics(run, labels) for name, run in store.data.items() if run.get("items")}
    hdr = ("| run | n | pkg acc | pkg P/R | person acc | person P/R | carry acc | vehicle acc | phone acc "
           "| mean acc | JSON fail | p50 ms | p95 ms | in tok | out tok | $/1k frames |")
    print(hdr)
    print("|" + "---|" * (hdr.count("|") - 1))
    for name, m in rows.items():
        P, Pe = m["package_visible"], m["person_present"]
        print(f"| {name} | {m['n']} | {pct(P['acc'])} | {pct(P['prec'])}/{pct(P['rec'])} | {pct(Pe['acc'])} | "
              f"{pct(Pe['prec'])}/{pct(Pe['rec'])} | {pct(m['person_carrying_package']['acc'])} | "
              f"{pct(m['vehicle_present']['acc'])} | {pct(m['phone_screen_shown']['acc'])} | {pct(m['mean_acc'])} | "
              f"{m['parse_fail'] + m['api_fail']}/{m['n']} | {m.get('lat_p50', 0):.0f} | {m.get('lat_p95', 0):.0f} | "
              f"{m.get('in_tok', 0):.0f} | {m.get('out_tok', 0):.0f} | ${m.get('usd_per_1k', 0):.3f} |")
    print(f"\nTotal Bedrock spend recorded by this script: ${store.spent():.4f}")
    (HERE / "results_metrics.json").write_text(json.dumps(rows, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="")
    ap.add_argument("--probe", action="store_true", help="one image per base model, print raw output")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--budget", type=float, default=1.30)
    ap.add_argument("--force", action="store_true", help="re-run runs that already exist")
    args = ap.parse_args()

    all_labels = json.loads((HERE / "labels.json").read_text())
    labels = {x["id"]: x for x in all_labels if not x.get("excluded")}
    items = list(labels.values())
    store = Store()
    import boto3
    from botocore.config import Config
    client = boto3.client("bedrock-runtime", region_name=REGION,
                          config=Config(retries={"max_attempts": 1}, read_timeout=120))

    if args.probe:
        it = labels["place_02"]
        for name in ["nova-lite", "nova-pro", "nova-2-lite", "haiku-4.5", "haiku-5.5", "sonnet-5.5", "sonnet-4.6"]:
            model_id, inf, extra, side, pkey = RUNS[name]
            img, size = load_image(HERE / "images" / it["file"], side)
            try:
                resp, ms = call(client, model_id, inf, extra, PROMPTS[pkey], img)
                u = resp["usage"]
                text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"] if "text" in c)
                c = cost_of({"model_id": model_id, "input_tokens": u["inputTokens"], "output_tokens": u["outputTokens"]})
                kinds = [list(c_.keys())[0] for c_ in resp["output"]["message"]["content"]]
                print(f"{name}: {ms:.0f} ms in={u['inputTokens']} out={u['outputTokens']} ${c:.5f} "
                      f"blocks={kinds} stop={resp.get('stopReason')}\n   {text.strip()[:300]!r}")
            except Exception as e:  # noqa: BLE001
                print(f"{name}: ERROR {str(e)[:300]}")
        return 0

    if args.runs:
        names = [n.strip() for n in args.runs.split(",") if n.strip()]
        if args.force:
            for n in names:
                store.data.pop(n, None)
        todo = [n for n in names if n not in store.data or len(store.data[n]["items"]) < len(items)
                or any("api_error" in r for r in store.data[n]["items"])]
        print(f"already spent ${store.spent():.4f}; running {todo} on {len(items)} images (cap ${args.budget})")
        with ThreadPoolExecutor(max(1, len(todo))) as ex:
            for f in [ex.submit(run_one, store, client, n, items, args.budget) for n in todo]:
                f.result()
    report(store, labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
