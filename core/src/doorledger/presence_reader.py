"""Find and decode presence QR codes in a doorbell video frame (BGR, OpenCV).

Pipeline, cheapest first, stopping as soon as something decodes:

1. ``QRCodeDetector.detectAndDecodeMulti`` on the grayscale frame.
2. Same on a CLAHE-equalised frame (backlit porches, dim screens).
3. Candidate regions: ``detectMulti`` from the classic detector and the
   ArUco-based detector (more robust finder-pattern search); each region is
   cropped with a margin, upscaled (x2, x3, x4 with INTER_CUBIC), optionally
   unsharp-masked, and decoded on its own.  Small codes (< ~3 px/module) are the common failure on a wide
   doorbell lens and upscaling a crop is far cheaper than upscaling the frame.
4. Optional bright-region search: phones at the door are usually the brightest
   rectangle in the frame; the largest bright blobs are tried as crops.

Everything returns ``Detection(text, points)`` with ``points`` = 4x2 float array
in original-frame pixel coordinates.

Measured (eval/presence/RESULTS.md): ~40 ms for a 1080p frame when the code is
found in stage 1, up to the ``time_budget_ms`` (default 250 ms) when every
fallback runs on a frame with no readable code.  In a live stream, run it on
every 2nd-3rd frame or in a worker thread.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

_CLAHE = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))


@dataclass(slots=True)
class Detection:
    text: str
    points: np.ndarray  # (4, 2) float32, frame coordinates
    stage: str = ""

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        x0, y0 = self.points.min(axis=0)
        x1, y1 = self.points.max(axis=0)
        return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


@dataclass(slots=True)
class ReadResult:
    detections: list[Detection] = field(default_factory=list)
    elapsed_ms: float = 0.0
    stages_tried: list[str] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [d.text for d in self.detections]


class PresenceReader:
    """Reusable reader (detectors are constructed once)."""

    def __init__(
        self,
        *,
        use_aruco: bool = True,
        use_bright_regions: bool = True,
        upscales: tuple[float, ...] = (2.0, 3.0, 4.0),
        max_candidates: int = 6,
        time_budget_ms: float = 250.0,
    ) -> None:
        self.qr = cv2.QRCodeDetector()
        self.aruco = None
        if use_aruco and hasattr(cv2, "QRCodeDetectorAruco"):
            try:
                self.aruco = cv2.QRCodeDetectorAruco()
            except cv2.error:  # pragma: no cover
                self.aruco = None
        self.use_bright_regions = use_bright_regions
        self.upscales = upscales
        self.max_candidates = max_candidates
        self.time_budget_ms = time_budget_ms

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _decode_multi(det, img: np.ndarray) -> list[tuple[str, np.ndarray]]:
        try:
            ok, texts, pts, _ = det.detectAndDecodeMulti(img)
        except cv2.error:
            return []
        if not ok or pts is None:
            return []
        return [(t, p.reshape(4, 2)) for t, p in zip(texts, pts) if t]

    @staticmethod
    def _detect_multi(det, img: np.ndarray) -> list[np.ndarray]:
        try:
            ok, pts = det.detectMulti(img)
        except cv2.error:
            return []
        if not ok or pts is None:
            return []
        return [p.reshape(4, 2) for p in pts]

    def _decode_crop(
        self, gray: np.ndarray, quad_or_box: np.ndarray, margin: float = 0.6
    ) -> tuple[str, np.ndarray] | None:
        h, w = gray.shape[:2]
        x0, y0 = quad_or_box.min(axis=0)
        x1, y1 = quad_or_box.max(axis=0)
        side = max(x1 - x0, y1 - y0, 8.0)
        m = side * margin
        cx0, cy0 = int(max(0, x0 - m)), int(max(0, y0 - m))
        cx1, cy1 = int(min(w, x1 + m)), int(min(h, y1 + m))
        crop = gray[cy0:cy1, cx0:cx1]
        if crop.size == 0:
            return None
        tried: set[float] = set()
        for s in self.upscales:
            # never blow a crop up past ~900 px; it only slows the decoder down
            s = max(1.0, min(s, 900.0 / max(crop.shape)))
            if s in tried:
                continue
            tried.add(s)
            up = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            # unsharp mask undoes part of the optical + upscale blur; measured on
            # synthetic doorbell frames it beats CLAHE / Otsu / adaptive variants
            soft = cv2.GaussianBlur(up, (0, 0), s * 0.5)
            sharp = cv2.addWeighted(up, 1.8, soft, -0.8, 0)
            for img in (up, sharp):
                try:
                    text, pts, _ = self.qr.detectAndDecode(img)
                except cv2.error:
                    text, pts = "", None
                if text and pts is not None:
                    pts = pts.reshape(4, 2) / s + np.array([cx0, cy0], dtype=np.float32)
                    return text, pts.astype(np.float32)
        return None

    @staticmethod
    def _bright_regions(gray: np.ndarray, k: int) -> list[np.ndarray]:
        """Largest bright, roughly rectangular blobs (phone screens)."""
        scale = 480.0 / max(gray.shape)
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        thr = max(170, int(np.percentile(small, 97)))
        _, mask = cv2.threshold(small, thr - 1, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        boxes = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 30 or w < 5 or h < 5:
                continue
            fill = area / float(w * h)
            if fill < 0.45:
                continue
            boxes.append((area, x, y, w, h))
        boxes.sort(reverse=True)
        out = []
        for _, x, y, w, h in boxes[:k]:
            q = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32) / scale
            out.append(q)
        return out

    @staticmethod
    def _dedupe(found: list[Detection]) -> list[Detection]:
        out: list[Detection] = []
        for d in found:
            c = d.points.mean(axis=0)
            if any(o.text == d.text and np.linalg.norm(o.points.mean(axis=0) - c) < 20 for o in out):
                continue
            out.append(d)
        return out

    # ------------------------------------------------------------------ public
    def read(self, frame: np.ndarray, *, exhaustive: bool = False) -> ReadResult:
        """Decode every QR in ``frame`` (BGR or gray). Stops at the first stage
        that yields a result unless ``exhaustive``."""
        t0 = time.perf_counter()
        res = ReadResult()
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        def elapsed() -> float:
            return (time.perf_counter() - t0) * 1000.0

        def done() -> bool:
            return bool(res.detections) and not exhaustive

        # 1. plain full frame
        res.stages_tried.append("full")
        for t, p in self._decode_multi(self.qr, gray):
            res.detections.append(Detection(t, p.astype(np.float32), "full"))

        # 2. CLAHE full frame
        if not done():
            res.stages_tried.append("clahe")
            eq = _CLAHE.apply(gray)
            for t, p in self._decode_multi(self.qr, eq):
                res.detections.append(Detection(t, p.astype(np.float32), "clahe"))

        # 3. candidate regions -> crop + upscale
        if not done() and elapsed() < self.time_budget_ms:
            res.stages_tried.append("candidates")
            cands = self._detect_multi(self.qr, gray)
            if self.aruco is not None:
                cands += self._detect_multi(self.aruco, gray)
            for q in cands[: self.max_candidates]:
                if elapsed() > self.time_budget_ms:
                    break
                hit = self._decode_crop(gray, q)
                if hit:
                    res.detections.append(Detection(hit[0], hit[1], "candidate"))
                    if not exhaustive:
                        break

        # 4. bright rectangles (phone screens)
        if not done() and self.use_bright_regions and elapsed() < self.time_budget_ms:
            res.stages_tried.append("bright")
            for q in self._bright_regions(gray, self.max_candidates):
                if elapsed() > self.time_budget_ms:
                    break
                hit = self._decode_crop(gray, q, margin=0.15)
                if hit:
                    res.detections.append(Detection(hit[0], hit[1], "bright"))
                    if not exhaustive:
                        break

        res.detections = self._dedupe(res.detections)
        res.elapsed_ms = elapsed()
        return res


_default: PresenceReader | None = None


def read_qr_codes(frame: np.ndarray, **kwargs) -> list[Detection]:
    """Convenience wrapper using a module-level :class:`PresenceReader`."""
    global _default
    if _default is None:
        _default = PresenceReader()
    return _default.read(frame, **kwargs).detections


__all__ = ["Detection", "PresenceReader", "ReadResult", "read_qr_codes"]
