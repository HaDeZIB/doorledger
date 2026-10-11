"""Watcher pipeline on synthetic frames: motion gate, evidence files, porch events, presence QR."""

from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pytest
import segno
from doorledger import presence
from doorledger.clock import SimClock
from doorledger.domain import ObservationKind, Source
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.notify import ConsoleNotifier
from doorledger.responder import Responder, TemplateWriter
from doorledger.vision import ScriptedVision
from doorledger.watcher import Frame, ReplaySource, Watcher
from doorledger.weather import AmbientTemperature

T_EPOCH = 1_760_200_000.0  # wall-clock capture time used for presence codes
AT = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)
VID = "V-MORNING"
SECRET = bytes(range(32))
NOTHING = {"package_visible": False, "person_present": False, "confidence": 0.9}
PACKAGE = {"package_visible": True, "confidence": 0.9, "note": "box on mat"}


def make_engine() -> Engine:
    hh = demo_household()
    return Engine(hh, Ledger(":memory:", household=hh.id),
                  Responder(hh, ConsoleNotifier(), TemplateWriter()), SimClock(AT, speed=0),
                  AmbientTemperature(hh.lat, hh.lon, override_c=20.0),
                  device={"id": "dev-front", "online": True})


def make_watcher(engine, vision, tmp_path, **kw) -> Watcher:
    kw.setdefault("redact_faces", False)
    return Watcher(engine, vision, tmp_path, **kw)


def plain(value: int = 120) -> np.ndarray:
    return np.full((360, 640, 3), value, np.uint8)


def qr_frame(code: str) -> np.ndarray:
    q = segno.make_qr(code, error="m")
    m = np.pad(np.array(q.matrix, dtype=np.uint8), 4)
    qr = cv2.resize(np.where(m == 1, 0, 255).astype(np.uint8), None, fx=8, fy=8,
                    interpolation=cv2.INTER_NEAREST)
    frame = np.full((720, 1280), 120, np.uint8)
    frame[200:200 + qr.shape[0], 500:500 + qr.shape[1]] = qr
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


async def stream(images, *, source=Source.RING_LIVE, captured_at=None):
    for i, img in enumerate(images):
        yield Frame(AT + timedelta(seconds=i), img, source, captured_at)


# ------------------------------------------------------------------ motion gate


async def test_identical_frames_skip_vision_and_reclassify_after_max_reuse(tmp_path):
    engine = make_engine()
    vision = ScriptedVision([NOTHING, PACKAGE])
    w = make_watcher(engine, vision, tmp_path, max_reuse=4)
    await w.process(stream([plain()] * 6))
    # frame 1: classified; frames 2-5: reused (4 = max_reuse); frame 6: classified again
    assert (w.vision_calls, w.vision_skipped) == (2, 4)
    assert vision.i == 2
    assert w.last_label.package_visible is True
    assert w.frames_seen == 6


async def test_changed_frames_always_call_vision(tmp_path):
    vision = ScriptedVision([NOTHING])
    w = make_watcher(make_engine(), vision, tmp_path)
    await w.process(stream([plain(0), plain(255), plain(0), plain(255)]))
    assert (w.vision_calls, w.vision_skipped) == (4, 0)


async def test_reused_label_drives_porch_tracker(tmp_path):
    engine = make_engine()
    w = make_watcher(engine, ScriptedVision([PACKAGE]), tmp_path)
    emitted = await w.process(stream([plain()] * 4))
    assert w.vision_calls == 1  # 3 of the 4 frames reused the label
    assert [o.kind for o in emitted] == [ObservationKind.PACKAGE_DROPPED]
    o = emitted[0]
    assert o.at == AT + timedelta(seconds=2)  # third frame completes 3-of-5
    assert o.device_id == "dev-front" and o.source == Source.RING_LIVE
    assert o.evidence_path.startswith("evidence/captured/")
    assert (tmp_path / o.evidence_path.removeprefix("evidence/")).is_file()
    assert engine.observations == emitted  # ingested into the engine


async def test_evidence_written_only_for_confirmed_observations(tmp_path):
    w = make_watcher(make_engine(), ScriptedVision([NOTHING]), tmp_path, subdir="session1")
    assert await w.process(stream([plain(10), plain(200), plain(10)])) == []
    assert list((tmp_path / "session1").glob("*.jpg")) == []  # nothing happened: nothing stored
    assert w.frames_persisted == 0


async def test_evidence_file_matches_observation(tmp_path):
    engine = make_engine()
    w = make_watcher(engine, ScriptedVision([PACKAGE]), tmp_path, subdir="session1")
    emitted = await w.process(stream([plain()] * 5))
    files = sorted((tmp_path / "session1").glob("*.jpg"))
    assert len(files) == 1 and w.frames_persisted == 1
    assert emitted[0].evidence_path == f"evidence/session1/{files[0].name}"
    assert files[0].name.startswith((AT + timedelta(seconds=2)).strftime("%Y%m%dT%H%M%S"))
    img = cv2.imread(str(files[0]))
    assert img is not None and img.shape == (360, 640, 3)


async def test_face_redaction_on_blank_frames_is_noop(tmp_path):
    w = Watcher(make_engine(), ScriptedVision([PACKAGE]), tmp_path)  # redact_faces=True
    emitted = await w.process(stream([plain()] * 3))
    assert w.redactor is not None
    assert w.faces_redacted == 0
    assert len(emitted) == 1
    assert len(list((tmp_path / "captured").glob("*.jpg"))) == 1


def test_purge_evidence_removes_only_old_frames(tmp_path):
    import os
    import time

    from doorledger.watcher import purge_evidence

    old, new = tmp_path / "old.jpg", tmp_path / "new.jpg"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    past = time.time() - 3 * 86400
    os.utime(old, (past, past))
    assert purge_evidence(tmp_path, older_than_days=2) == 1
    assert not old.exists() and new.exists()


async def test_trackers_are_per_source(tmp_path):
    w = make_watcher(make_engine(), ScriptedVision([NOTHING]), tmp_path)
    assert w.tracker(Source.RING_LIVE) is w.tracker(Source.RING_LIVE)
    assert w.tracker(Source.RING_LIVE) is not w.tracker(Source.OWN_FOOTAGE)


# ------------------------------------------------------------------ presence codes


async def test_presence_code_checks_in_once_with_replay_protection(tmp_path):
    engine = make_engine()
    engine.visit_secrets[VID] = SECRET
    code = presence.make_compact_code(VID, SECRET, "in", at=T_EPOCH)
    w = make_watcher(engine, ScriptedVision([NOTHING]), tmp_path)
    img = qr_frame(code)
    emitted = await w.process(stream([img] * 4, source=Source.OWN_FOOTAGE, captured_at=T_EPOCH))
    checkins = [o for o in emitted if o.kind == ObservationKind.PRESENCE_CHECK_IN]
    assert len(checkins) == 1  # frames 2 and 4 both decode it; the second is a replay
    ci = checkins[0]
    assert ci.visit_id == VID and ci.source == Source.OWN_FOOTAGE
    assert ci.at == AT + timedelta(seconds=1)  # presence is read on every 2nd frame
    assert ci.detail["method"] == "signed_code" and ci.detail["skew"] == 0
    assert len(w.used_codes) == 1


async def test_presence_check_out_after_check_in(tmp_path):
    engine = make_engine()
    engine.visit_secrets[VID] = SECRET
    c_in = qr_frame(presence.make_compact_code(VID, SECRET, "in", at=T_EPOCH))
    c_out = qr_frame(presence.make_compact_code(VID, SECRET, "out", at=T_EPOCH))
    w = make_watcher(engine, ScriptedVision([NOTHING]), tmp_path)
    emitted = await w.process(stream([c_in, c_in, c_out, c_out], captured_at=T_EPOCH))
    assert [o.kind for o in emitted] == [ObservationKind.PRESENCE_CHECK_IN,
                                         ObservationKind.PRESENCE_CHECK_OUT]


async def test_presence_uses_frame_time_when_capture_time_missing(tmp_path):
    engine = make_engine()
    engine.visit_secrets[VID] = SECRET
    code = presence.make_compact_code(VID, SECRET, "in", at=AT.timestamp())
    w = make_watcher(engine, ScriptedVision([NOTHING]), tmp_path)
    emitted = await w.process(stream([qr_frame(code)] * 2))
    assert [o.kind for o in emitted] == [ObservationKind.PRESENCE_CHECK_IN]


async def test_presence_code_from_another_time_is_rejected(tmp_path):
    engine = make_engine()
    engine.visit_secrets[VID] = SECRET
    stale = presence.make_compact_code(VID, SECRET, "in", at=T_EPOCH - 120)  # 8 steps old
    w = make_watcher(engine, ScriptedVision([NOTHING]), tmp_path)
    emitted = await w.process(stream([qr_frame(stale)] * 2, captured_at=T_EPOCH))
    assert emitted == []


async def test_presence_reader_not_run_without_visit_secrets(tmp_path):
    w = make_watcher(make_engine(), ScriptedVision([NOTHING]), tmp_path)

    def boom(_frame):  # pragma: no cover - must not be called
        raise AssertionError("reader called without any expected visit")

    w.reader.read = boom
    assert await w.process(stream([plain()] * 4)) == []


async def test_burst_mode_reads_presence_on_every_frame(tmp_path):
    engine = make_engine()
    engine.visit_secrets[VID] = SECRET
    code = presence.make_compact_code(VID, SECRET, "in", at=T_EPOCH)
    w = make_watcher(engine, ScriptedVision([NOTHING]), tmp_path)
    emitted = await w.process(stream([qr_frame(code)], captured_at=T_EPOCH), presence_every=1)
    assert [o.kind for o in emitted] == [ObservationKind.PRESENCE_CHECK_IN]
    assert emitted[0].at == AT
    assert emitted[0].evidence_path.startswith("evidence/captured/")


# ------------------------------------------------------------------ replay source


async def test_replay_source_steps_and_stamps(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(8):
        cv2.imwrite(str(frames_dir / f"{i:03d}.jpg"), plain(i * 30))
    src = ReplaySource(frames_dir, AT, fps=1.0, capture_fps=2.0, limit=3,
                       recorded_start=T_EPOCH)
    got = [f async for f in src.frames()]
    assert len(got) == 3 and src.step == 2
    assert [f.at for f in got] == [AT + timedelta(seconds=i) for i in range(3)]
    assert [f.captured_at for f in got] == pytest.approx([T_EPOCH, T_EPOCH + 1, T_EPOCH + 2])
    assert got[0].image.shape == (360, 640, 3)
