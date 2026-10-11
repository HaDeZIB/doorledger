"""Scene understanding for doorbell frames via Amazon Bedrock (Converse API).

The model gets one or more frames and must answer with a strict JSON object. We ask for
facts only ("is a package visible on the porch floor?"), never for judgements about the
visit — reconciliation stays deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .porch import FrameLabel

PROMPT = """You are the perception module of a home-care verification system watching a front-door camera.
Describe ONLY what is visible in the image. Answer with a single JSON object and nothing else:
{
  "package_visible": bool,          // a parcel/box/bag/envelope/cooler RESTING on the floor, mat or step. false if every parcel is in someone's hands
  "person_present": bool,           // any person visible near the door, including partly visible or seen from behind
  "person_carrying_package": bool,  // a person is holding a parcel/box/delivery bag in their hands or arms (not a purse or backpack)
  "vehicle_present": bool,          // a car/van/truck visible in the driveway or street close to the house
  "phone_screen_shown": bool,       // the lit DISPLAY of a phone faces the camera (you can see the screen content). false if you only see the back/camera side of a phone
  "phone_code_digits": string|null, // if a phone screen facing the camera shows a large 6-digit number, those 6 digits; else null
  "confidence": number,             // 0..1, your overall confidence
  "note": string                    // <= 12 words, plain description
}
Doorbell cameras are wide-angle: objects near the edges look stretched. Small devices, pucks or doormats are not parcels."""

# Chosen in eval/vision/RESULTS.md: 54/54 correct on all fields, ~$0.37 per 1k frames.
DEFAULT_MODEL = os.environ.get("DOORLEDGER_VISION_MODEL", "us.amazon.nova-2-lite-v1:0")


class VisionClassifier(Protocol):
    def classify(self, image_jpeg: bytes, at: datetime, evidence_path: str | None = None) -> FrameLabel: ...


def _parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"model did not return JSON: {text[:200]!r}")
    return json.loads(match.group(0))


def label_from_json(data: dict[str, Any], at: datetime, evidence_path: str | None) -> FrameLabel:
    return FrameLabel(
        at=at,
        package_visible=bool(data.get("package_visible")),
        person_present=bool(data.get("person_present")),
        person_carrying_package=bool(data.get("person_carrying_package")),
        vehicle_present=bool(data.get("vehicle_present")),
        confidence=float(data.get("confidence", 0.8)),
        note=data.get("note"),
        evidence_path=evidence_path,
        extra={"phone_screen_shown": bool(data.get("phone_screen_shown")),
               "phone_code_digits": data.get("phone_code_digits")},
    )


@dataclass
class UsageStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: float = 0.0


class BedrockVision:
    def __init__(self, model_id: str = DEFAULT_MODEL, region: str | None = None) -> None:
        import boto3

        self.model_id = model_id
        self.client = boto3.client("bedrock-runtime",
                                   region_name=region or os.environ.get("AWS_REGION", "us-east-1"))
        self.usage = UsageStats()

    def classify(self, image_jpeg: bytes, at: datetime, evidence_path: str | None = None) -> FrameLabel:
        started = time.perf_counter()
        resp = self.client.converse(
            modelId=self.model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": image_jpeg}}},
                    {"text": PROMPT},
                ],
            }],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
        self.usage.calls += 1
        self.usage.total_latency_ms += (time.perf_counter() - started) * 1000
        u = resp.get("usage", {})
        self.usage.input_tokens += u.get("inputTokens", 0)
        self.usage.output_tokens += u.get("outputTokens", 0)
        text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
        return label_from_json(_parse(text), at, evidence_path)


class ScriptedVision:
    """Deterministic stand-in for tests and offline demos: returns labels from a timeline."""

    def __init__(self, labels: list[dict[str, Any]]) -> None:
        self.labels = labels
        self.i = 0

    def classify(self, image_jpeg: bytes, at: datetime, evidence_path: str | None = None) -> FrameLabel:
        data = self.labels[min(self.i, len(self.labels) - 1)]
        self.i += 1
        return label_from_json(data, at, evidence_path)


class CachingVision:
    """Record/replay wrapper around a real classifier, keyed by the SHA-256 of the exact JPEG.

    * record: call the inner model (e.g. Bedrock) and store its JSON answer per frame;
    * replay: answer from the cache so the offline demo runs real Ring frames through the
      real pipeline with the labels Bedrock actually produced — no AWS credentials needed.
    A replay miss returns an empty scene (and is counted), never an invented detection.
    """

    def __init__(self, cache_path: str | Path, inner: VisionClassifier | None = None) -> None:
        self.path = Path(cache_path)
        self.inner = inner
        self.cache: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text()) if self.path.exists() else {})
        self.hits = self.misses = 0

    def classify(self, image_jpeg: bytes, at: datetime, evidence_path: str | None = None) -> FrameLabel:
        import hashlib

        key = hashlib.sha256(image_jpeg).hexdigest()
        if key in self.cache:
            self.hits += 1
            return label_from_json(self.cache[key], at, evidence_path)
        self.misses += 1
        if self.inner is None:
            return label_from_json({"confidence": 0.0, "note": "not in vision cache"}, at,
                                   evidence_path)
        label = self.inner.classify(image_jpeg, at, evidence_path)
        self.cache[key] = {
            "package_visible": label.package_visible, "person_present": label.person_present,
            "person_carrying_package": label.person_carrying_package,
            "vehicle_present": label.vehicle_present, "confidence": label.confidence,
            "note": label.note, **(label.extra or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        return label
