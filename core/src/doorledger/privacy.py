"""Privacy filter for evidence frames.

Order of operations for every frame (see watcher.Watcher.process):
1. the device's Ring privacy zones are blacked out (never analyzed or stored);
2. faces are pixelated on-device (OpenCV YuNet, ~230 KB) — this redacted JPEG is the only
   thing sent to Bedrock and the only thing ever written to disk;
3. a frame is stored only when it backs a confirmed observation, and expires after the
   retention window. The un-redacted frame stays in memory, used only by the on-device
   presence-code reader. YuNet can miss faces (fails open); that limitation is documented.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("doorledger.privacy")

MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"


class FaceRedactor:
    def __init__(self, score_threshold: float = 0.6, block: int = 12) -> None:
        self.block = block
        self.detector = None
        if MODEL.exists() and hasattr(cv2, "FaceDetectorYN"):
            self.detector = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), score_threshold)
        else:  # pragma: no cover
            log.warning("face model unavailable; evidence frames will not be redacted")

    def faces(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self.detector is None:
            return []
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, found = self.detector.detect(image)
        if found is None:
            return []
        boxes = []
        for row in found:
            x, y, bw, bh = (int(v) for v in row[:4])
            pad_w, pad_h = int(bw * 0.2), int(bh * 0.25)
            boxes.append((max(x - pad_w, 0), max(y - pad_h, 0),
                          min(bw + 2 * pad_w, w), min(bh + 2 * pad_h, h)))
        return boxes

    def redact(self, image: np.ndarray) -> tuple[np.ndarray, int]:
        """Return a copy with faces pixelated, and how many faces were redacted."""
        boxes = self.faces(image)
        if not boxes:
            return image, 0
        out = image.copy()
        for x, y, bw, bh in boxes:
            roi = out[y:y + bh, x:x + bw]
            if roi.size == 0:
                continue
            small = cv2.resize(roi, (max(bw // self.block, 1), max(bh // self.block, 1)),
                               interpolation=cv2.INTER_LINEAR)
            out[y:y + bh, x:x + bw] = cv2.resize(small, (bw, bh), interpolation=cv2.INTER_NEAREST)
        return out, len(boxes)


def apply_privacy_zones(image: np.ndarray, zones: list[dict] | None) -> np.ndarray:
    """Black out the device's Ring privacy zones BEFORE any analysis or storage.

    Ring's UX guidance: video inside a customer's privacy zones must not be analyzed or stored.
    Zones come from ``GET /v1/devices/{id}/configurations`` →
    ``image_enhancements.privacy_zones`` (same shape as motion zones: normalized vertices).
    """
    if not zones:
        return image
    h, w = image.shape[:2]
    out = image.copy()
    for zone in zones:
        pts = [(int(v["x"] * w), int(v["y"] * h)) for v in zone.get("vertices") or []]
        if len(pts) >= 3:
            cv2.fillPoly(out, [np.array(pts, dtype=np.int32)], (0, 0, 0))
    return out


def privacy_zones_from_configurations(configurations: dict | None) -> list[dict]:
    cfg = configurations or {}
    return list(((cfg.get("image_enhancements") or {}).get("privacy_zones")) or [])
