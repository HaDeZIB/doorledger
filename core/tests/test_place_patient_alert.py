"""scripts/place_patient_alert.py: the filming trigger for Rosa's real call + SMS.

Offline only: Amazon Connect and Amazon SNS are stubs, and boto3 is never asked for a client.
"""

import importlib.util
import io
from pathlib import Path

import pytest
from doorledger import wording
from doorledger.household import demo_household

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("place_patient_alert",
                                               ROOT / "scripts" / "place_patient_alert.py")
ppa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ppa)

PHONE = "+5218330001234"  # fictional
SOURCE = "+19370005555"  # fictional
ENV = {
    "DOORLEDGER_CONNECT_INSTANCE_ID": "inst-test", "DOORLEDGER_CONNECT_FLOW_ID": "flow-test",
    "DOORLEDGER_CONNECT_SOURCE_NUMBER": SOURCE, "DOORLEDGER_VOICE_TO": PHONE,
    "DOORLEDGER_SMS_TO": PHONE, "AWS_REGION": "us-east-1",
}
WHO = wording.People.of(demo_household())


class FakeConnect:
    def __init__(self, answered=True, fail=False):
        self.started, self.described, self.answered, self.fail = [], 0, answered, fail

    def start_outbound_voice_contact(self, **kw):
        if self.fail:
            raise RuntimeError(f"InvalidParameter: {kw['DestinationPhoneNumber']} not allowed")
        self.started.append(kw)
        return {"ContactId": "contact-test-1"}

    def describe_contact(self, **kw):
        self.described += 1
        if self.described < 2:
            return {"Contact": {}}  # still ringing
        if self.answered:
            return {"Contact": {"ConnectedToSystemTimestamp": "t"}}
        return {"Contact": {"DisconnectTimestamp": "t"}}


class FakeSNS:
    def __init__(self):
        self.published = []

    def publish(self, **kw):
        self.published.append(kw)
        return {"MessageId": "m-1"}


@pytest.fixture(autouse=True)
def no_boto(monkeypatch):
    import boto3

    def boom(*a, **k):
        raise AssertionError("the script must not create a real AWS client in tests")

    monkeypatch.setattr(boto3, "client", boom)


def run(*argv, env=None, connect=None, sns=None):
    out = io.StringIO()
    code = ppa.main([*argv, "--env-file", "/nonexistent/.env", "--countdown", "0"],
                    environ=dict(ENV if env is None else env), connect_client=connect,
                    sns_client=sns, sleep=lambda s: None, out=out)
    return code, out.getvalue()


def test_mask_keeps_only_last_two_digits():
    assert ppa.mask(PHONE) == "+***********34"
    assert ppa.mask_text(f"to {PHONE} now") == "to +***********34 now"


def test_dry_run_prints_exact_templates_and_sends_nothing():
    connect, sns = FakeConnect(), FakeSNS()
    code, out = run("--dry-run", connect=connect, sns=sns)
    assert code == 0
    call = wording.patient_call("porch_patient", WHO, True, "es")
    sms = wording.patient_sms("porch_patient", WHO, True, "es")
    assert call.ssml in out and f"[Demo · para Rosa] {sms}" in out
    assert connect.started == [] and sns.published == []
    assert "1234" not in out.replace("+***********34", "")  # numbers masked everywhere
    assert "DOORLEDGER_VOICE_TO                set (+***********34)" in out


def test_dry_run_works_without_settings():
    code, out = run("--dry-run", env={})
    assert code == 0 and "not set" in out and "Dry run: nothing was sent" in out


@pytest.mark.parametrize("argv,missing", [
    ((), "DOORLEDGER_VOICE_TO"), (("--call",), "DOORLEDGER_VOICE_TO"),
    (("--sms",), "DOORLEDGER_SMS_TO")])
def test_refuses_without_destination(argv, missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    connect, sns = FakeConnect(), FakeSNS()
    code, out = run(*argv, env=env, connect=connect, sns=sns)
    assert code == 2 and "refusing" in out and missing in out
    assert connect.started == [] and sns.published == []


def test_both_places_one_call_and_one_sms_then_reports_answered():
    connect, sns = FakeConnect(answered=True), FakeSNS()
    code, out = run(connect=connect, sns=sns)
    assert code == 0
    # exactly one call and one SMS: no re-call, nothing to Luis or Ana
    assert len(connect.started) == 1 and len(sns.published) == 1
    started = connect.started[0]
    assert started["DestinationPhoneNumber"] == PHONE and started["SourcePhoneNumber"] == SOURCE
    assert started["Attributes"]["ssml"] == wording.patient_call("porch_patient", WHO, True,
                                                                 "es").ssml
    pub = sns.published[0]
    assert pub["PhoneNumber"] == PHONE
    assert pub["Message"] == "[Demo · para Rosa] " + wording.patient_sms("porch_patient", WHO,
                                                                         True, "es")
    assert "contact-test-1" in out and "outcome: answered" in out
    assert PHONE not in out and "1234" not in out.replace("+***********34", "")


def test_call_only_reports_no_answer_and_never_texts():
    connect, sns = FakeConnect(answered=False), FakeSNS()
    code, out = run("--call", connect=connect, sns=sns)
    assert code == 0 and len(connect.started) == 1 and sns.published == []
    assert "outcome: no_answer" in out


def test_failed_call_in_call_only_mode_masks_the_number_and_sends_no_sms():
    connect, sns = FakeConnect(fail=True), FakeSNS()
    code, out = run("--call", connect=connect, sns=sns)
    assert code == 1 and sns.published == []
    assert "CALL  failed" in out and PHONE not in out


def test_too_late_kind_uses_the_safe_wording():
    connect, sns = FakeConnect(), FakeSNS()
    code, _ = run("--kind", "too_late", connect=connect, sns=sns)
    assert code == 0
    ssml = connect.started[0]["Attributes"]["ssml"]
    assert "No la tire" in ssml and "llame a su farmacia o a Ana" in ssml
    assert "No la tire: guárdela en el refri." in sns.published[0]["Message"]


def test_env_file_never_overrides(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# c\nexport DOORLEDGER_SMS_TO="+100"\nAWS_REGION=eu-west-1 # x\nEMPTY=\n')
    env = {"AWS_REGION": "us-east-1"}
    assert ppa.load_env(f, env)
    assert env == {"AWS_REGION": "us-east-1", "DOORLEDGER_SMS_TO": "+100"}
