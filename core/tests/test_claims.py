"""Pharmacy exposure report (PDF) rendered from engine state."""

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest
from doorledger import claims
from doorledger.clock import SimClock
from doorledger.domain import (
    Expectation,
    ExpectationKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Source,
)
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.notify import ConsoleNotifier
from doorledger.responder import Responder, TemplateWriter
from doorledger.weather import AmbientTemperature

DAY = datetime(2026, 10, 11, tzinfo=UTC)


def t(hh: int, mm: int = 0) -> datetime:
    return DAY.replace(hour=hh, minute=mm)


def porch_cold_engine(evidence_root, *, with_visit: bool = False):
    """Roughly the ``porch_cold`` scenario: insulin left at -9 °C, compromised before pickup."""
    hh = demo_household()
    engine = Engine(hh, Ledger(":memory:", household=hh.id),
                    Responder(hh, ConsoleNotifier(), TemplateWriter()), SimClock(t(14), speed=0),
                    AmbientTemperature(hh.lat, hh.lon, override_c=-9.0))
    exp = Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin refill (pharmacy)",
                      t(13), t(17), carrier="Courier", tracking="DEMO-4471",
                      medication=MedicationProfile())
    engine.add_expectation(exp)
    visit = None
    if with_visit:
        visit = Expectation(ExpectationKind.CAREGIVER_VISIT, "Morning personal care", t(9), t(11),
                            caregiver="Maria", agency="BrightPath Home Care", planned_minutes=120,
                            visit_id="V-MORNING")
        engine.add_expectation(visit)
    (evidence_root / "captured").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(evidence_root / "captured" / "drop.jpg"), np.full((360, 640, 3), 90, np.uint8))
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14, 7), Source.RING_LIVE,
                              evidence_path="evidence/captured/drop.jpg"))
    for hh_, mm in ((14, 30), (14, 40), (14, 50)):
        engine.evaluate(t(hh_, mm))
    engine.clock.set(t(14, 55), 0)
    engine.ingest(Observation(ObservationKind.PACKAGE_REMOVED, t(14, 55), Source.RING_LIVE,
                              evidence_path="evidence/captured/missing.jpg"))
    return engine, exp, visit


@pytest.fixture
def paragraphs(monkeypatch):
    texts: list[str] = []
    real = claims.Paragraph

    def spy(text, *a, **kw):
        texts.append(text)
        return real(text, *a, **kw)

    monkeypatch.setattr(claims, "Paragraph", spy)
    return texts


def test_exposure_report_is_a_pdf(tmp_path, paragraphs):
    engine, exp, _ = porch_cold_engine(tmp_path)
    pdf = claims.exposure_report(engine, exp.id, tmp_path)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000
    joined = "\n".join(paragraphs)
    assert "Rosa Martínez" in joined and "DEMO-4471" in joined
    assert "Parcel left" in joined          # evidence frame that exists is embedded
    assert "Parcel taken inside" not in joined  # missing file is skipped, not a crash
    assert "Who was notified" in joined and "pharmacy_claim → Pharmacy" in joined


def test_exposure_report_before_drop(tmp_path):
    hh = demo_household()
    engine = Engine(hh, Ledger(":memory:", household=hh.id),
                    Responder(hh, ConsoleNotifier(), TemplateWriter()), SimClock(t(13), speed=0),
                    AmbientTemperature(hh.lat, hh.lon, override_c=20.0))
    exp = Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin", t(13), t(17))
    engine.add_expectation(exp)
    assert claims.exposure_report(engine, exp.id, tmp_path).startswith(b"%PDF")


def test_exposure_report_unknown_expectation(tmp_path):
    engine, _, _ = porch_cold_engine(tmp_path)
    with pytest.raises(KeyError):
        claims.exposure_report(engine, "exp_nope", tmp_path)


def test_exposure_report_lists_only_this_deliverys_actions(tmp_path, paragraphs):
    engine, exp, _ = porch_cold_engine(tmp_path, with_visit=True)
    # sanity: the missed morning visit produced a backup request in the ledger
    assert any(r["body"]["kind"] == "request_backup"
               for r in engine.ledger.records(kinds=["action"]))
    claims.exposure_report(engine, exp.id, tmp_path)
    notified = [p for p in paragraphs if " → " in p]
    assert notified, "expected the delivery's own notifications"
    assert not any("request_backup" in p or "BrightPath" in p for p in notified)
