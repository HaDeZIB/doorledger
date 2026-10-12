"""Fixed wording for Rosa (patient) and Luis (neighbor), and the hosted demo's copy of it."""

import re
import xml.etree.ElementTree as ET

import pytest
from doorledger import wording
from doorledger.demo_export import MOCK_MESSAGES, render
from doorledger.domain import Person
from doorledger.household import Household, Patient, demo_household

WHO = wording.People.of(demo_household())
MEDICAL = re.compile(r"insulin|medic|diabet|refriger|fridge|refri|farmac|pharmac|dosis|dose",
                     re.IGNORECASE)


def test_people_from_household():
    assert WHO == wording.People("Rosa", "Ana", "daughter", "Luis")
    assert WHO.family_es == "su hija Ana" and WHO.family_en == "her daughter Ana"


@pytest.mark.parametrize("cold", [True, False])
@pytest.mark.parametrize("purpose", ["porch_patient", "porch_compromised"])
def test_call_script_rules(purpose, cold):
    call = wording.patient_call(purpose, WHO, cold, "es")
    assert call.text.startswith("Hola, señora Rosa. Le llamamos de parte de su hija Ana.")
    assert call.text.count("Repito:") == 1
    key = ("métala a la casa y póngala en el refri" if purpose == "porch_patient"
           else "llame a su farmacia o a Ana")
    assert call.text.count(key) == 2  # the one action is said twice
    assert not any(ch.isdigit() for ch in call.text)
    assert "http" not in call.text and "No la use" not in call.text
    root = ET.fromstring(call.ssml)  # well-formed SSML
    assert root.tag == "speak"
    (prosody,) = list(root)
    assert prosody.tag == "prosody" and prosody.attrib == {"rate": "88%"}
    breaks = [b.attrib["time"] for b in prosody.iter("break")]
    assert breaks and set(breaks) <= {"600ms", "1s"}


def test_rosa_never_sent_onto_ice():
    cold = wording.patient_call("porch_patient", WHO, True, "es").text
    assert "Si hay hielo en el escalón, no salga sola." in cold
    assert "Le vamos a avisar a Luis para que le ayude." in cold
    assert "No tiene que contestar." in cold
    sms = wording.patient_sms("porch_patient", WHO, True, "es")
    assert "Si hay hielo en el escalón, no salga sola" in sms
    hot = wording.patient_sms("porch_patient", WHO, False, "es")
    assert "hielo" not in hot and "Si no puede salir, no se preocupe" in hot


@pytest.mark.parametrize("purpose", ["porch_patient", "porch_compromised", "porch_retrieved"])
@pytest.mark.parametrize("language", ["es", "en"])
def test_patient_sms_is_short_and_has_no_numbers_or_links(purpose, language):
    for cold in (True, False):
        msg = wording.patient_sms(purpose, WHO, cold, language)
        assert msg and len(msg) <= 280
        assert not any(ch.isdigit() for ch in msg)
        assert "http" not in msg and "DoorLedger" not in msg


def test_too_late_message_says_what_to_do_instead():
    """improvements-04 §1.1: never only "don't use your insulin" (missed doses are risky)."""
    msg = wording.patient_sms("porch_compromised", WHO, True, "es")
    assert "No la tire: guárdela en el refri." in msg
    assert "Antes de usarla, llame a su farmacia o a Ana." in msg
    assert "Si tiene otra insulina que no estuvo afuera, siga con esa." in msg
    assert "Ana ya sabe y le va a conseguir otra." in msg
    assert "No la use" not in msg and "reposición" not in msg


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("cold", [True, False])
def test_neighbor_message_reveals_no_medical_condition(language, cold):
    msg = wording.neighbor_sms(WHO, cold, 12, language)
    assert not MEDICAL.search(msg), msg
    assert "12 min" in msg
    if language == "en":
        assert f"must not stay out in the {'cold' if cold else 'heat'}" in msg


def test_wording_without_neighbor_or_family():
    hh = Household("hh", Patient("Elena Ruiz", 80, "Austin, TX", "America/Chicago"),
                   [Person("Elena Ruiz", "patient", escalation_order=1, language="es")])
    who = wording.People.of(hh)
    call = wording.patient_call("porch_patient", who, True, "es")
    assert call.text.startswith("Hola, señora Elena. Le llamamos del aviso de su timbre.")
    assert "Vamos a pedir ayuda." in call.text
    assert "Ana" not in call.text


def test_hosted_demo_messages_match_backend_templates():
    """The dashboard's mock mode shows lib/mock/messages.json. It must be what the backend
    sends; regenerate with scripts/export_mock_messages.py after changing any template."""
    assert MOCK_MESSAGES.read_text() == render(), (
        "web/dashboard/lib/mock/messages.json is stale: run "
        "`uv run --package doorledger python scripts/export_mock_messages.py`")


def test_hosted_demo_story_shape():
    import json

    rows = json.loads(MOCK_MESSAGES.read_text())["actions"]
    porch = [(r["at"], r["role"], r["channel"]) for r in rows if r["at"] >= "14:00"]
    assert porch[:4] == [("14:07", "patient", "voice"), ("14:07", "patient", "sms"),
                         ("14:12", "patient", "voice"), ("14:17", "neighbor", "sms")]
    assert all(not MEDICAL.search(r["message"]) for r in rows if r["role"] == "neighbor")
