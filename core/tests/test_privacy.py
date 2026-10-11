"""On-device face redaction for evidence frames."""

import numpy as np
from doorledger.privacy import MODEL, FaceRedactor


def test_model_is_bundled():
    assert MODEL.is_file()
    assert FaceRedactor().detector is not None


def test_redact_without_faces_returns_same_array_and_zero():
    img = np.full((360, 640, 3), 128, np.uint8)
    out, n = FaceRedactor().redact(img)
    assert n == 0
    assert out is img  # no copy when there is nothing to hide


def test_redact_noise_frame_without_faces():
    img = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    before = img.copy()
    out, n = FaceRedactor().redact(img)
    assert n == 0 and out is img
    assert np.array_equal(img, before)


def test_faces_empty_when_detector_missing():
    r = FaceRedactor()
    r.detector = None
    img = np.zeros((100, 100, 3), np.uint8)
    assert r.faces(img) == []
    out, n = r.redact(img)
    assert out is img and n == 0
