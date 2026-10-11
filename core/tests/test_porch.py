"""k-of-n debounce that turns flickering per-frame labels into discrete porch events."""

from datetime import UTC, datetime, timedelta

from doorledger.domain import ObservationKind, Source
from doorledger.porch import FrameLabel, PorchTracker

T0 = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)


def feed(tracker: PorchTracker, values: list[bool], field: str = "package_visible", **kw):
    out = []
    for i, v in enumerate(values):
        label = FrameLabel(at=T0 + timedelta(seconds=i), **{field: v}, **kw)
        out.append(tracker.push(label))
    return out


def flat(batches):
    return [o for batch in batches for o in batch]


def test_package_drop_needs_three_of_five():
    tr = PorchTracker("dev1", Source.RING_LIVE)
    batches = feed(tr, [True, True, True])
    assert batches[0] == [] and batches[1] == []
    assert [o.kind for o in batches[2]] == [ObservationKind.PACKAGE_DROPPED]
    o = batches[2][0]
    assert o.device_id == "dev1" and o.source == Source.RING_LIVE
    assert tr.package.state is True


def test_flicker_does_not_emit():
    tr = PorchTracker()
    # never more than 2 positives in any 5-frame window
    assert flat(feed(tr, [True, False, False, True, False, False, True, False, False, True])) == []
    assert tr.package.state is False


def test_one_missed_frame_does_not_emit_removal():
    tr = PorchTracker()
    feed(tr, [True] * 5)
    # a leg hides the parcel for a frame or two: 4 of 5 must be off to flip
    assert flat(feed(tr, [False, True, False, True, False, True])) == []
    assert tr.package.state is True


def test_removal_after_four_of_five_off():
    tr = PorchTracker()
    feed(tr, [True] * 5)
    batches = feed(tr, [False, False, False, False])
    assert flat(batches[:3]) == []
    assert [o.kind for o in batches[3]] == [ObservationKind.PACKAGE_REMOVED]


def test_low_confidence_frames_are_ignored():
    tr = PorchTracker(min_confidence=0.5)
    assert flat(feed(tr, [True] * 5, confidence=0.3)) == []
    assert len(tr.package.window) == 0  # not even counted toward the window
    batches = feed(tr, [True] * 3, confidence=0.9)
    assert [o.kind for o in flat(batches)] == [ObservationKind.PACKAGE_DROPPED]
    assert flat(batches)[0].confidence == 0.9


def test_seed_package_present_allows_removal_without_drop():
    tr = PorchTracker()
    tr.seed(package_present=True)
    batches = feed(tr, [False] * 4)
    assert [o.kind for o in flat(batches)] == [ObservationKind.PACKAGE_REMOVED]


def test_seed_default_is_empty_porch():
    tr = PorchTracker()
    tr.seed()
    assert flat(feed(tr, [False] * 6)) == []


def test_person_rising_edge_only():
    tr = PorchTracker()
    on = feed(tr, [True] * 3, field="person_present", person_carrying_package=True, note="courier")
    assert [o.kind for o in flat(on)] == [ObservationKind.PERSON_AT_DOOR]
    o = flat(on)[0]
    assert o.detail == {"carrying_package": True, "note": "courier"}
    assert flat(feed(tr, [True] * 3, field="person_present")) == []  # still there: no repeat
    assert flat(feed(tr, [False] * 5, field="person_present")) == []  # leaving: no event
    again = feed(tr, [True] * 3, field="person_present")
    assert [o.kind for o in flat(again)] == [ObservationKind.PERSON_AT_DOOR]


def test_vehicle_rising_edge_only():
    tr = PorchTracker()
    assert [o.kind for o in flat(feed(tr, [True] * 3, field="vehicle_present"))] == [
        ObservationKind.VEHICLE_ARRIVED]
    assert flat(feed(tr, [False] * 5, field="vehicle_present")) == []


def test_note_none_is_dropped_from_detail():
    tr = PorchTracker()
    o = flat(feed(tr, [True] * 3))[0]
    assert o.detail == {}


def test_evidence_path_falls_back_to_last_seen():
    tr = PorchTracker()
    tr.push(FrameLabel(at=T0, package_visible=True, evidence_path="evidence/a.jpg"))
    tr.push(FrameLabel(at=T0, package_visible=True))
    out = tr.push(FrameLabel(at=T0, package_visible=True))
    assert out[0].evidence_path == "evidence/a.jpg"


def test_simultaneous_signals_emit_in_one_frame():
    tr = PorchTracker()
    out = []
    for i in range(3):
        out += tr.push(FrameLabel(at=T0 + timedelta(seconds=i), package_visible=True,
                                  person_present=True, vehicle_present=True))
    assert [o.kind for o in out] == [ObservationKind.PERSON_AT_DOOR, ObservationKind.VEHICLE_ARRIVED,
                                     ObservationKind.PACKAGE_DROPPED]
    assert all(o.at == T0 + timedelta(seconds=2) for o in out)
