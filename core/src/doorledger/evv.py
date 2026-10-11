"""Electronic Visit Verification export.

The 21st Century Cures Act (Sec. 12006) requires EVV systems to capture six elements:
type of service, individual receiving the service, date, location, individual providing the
service, and time the service begins and ends. DoorLedger adds the verification method and
evidence reference so an auditor can see HOW presence was proven.
"""

from __future__ import annotations

import csv
import io
from zoneinfo import ZoneInfo

from .household import Household
from .reconcile import Reconciliation

COLUMNS = [
    "service_type", "recipient", "date", "location", "provider", "time_in", "time_out",
    "minutes_on_site", "planned_minutes", "status", "verification_method", "evidence",
]


def rows(r: Reconciliation, household: Household, service_type: str = "Personal care (T1019)"):
    tz = ZoneInfo(household.patient.timezone)
    for v in r.visits:
        e = v.expectation
        cin, cout = v.check_in, v.check_out
        if cin is None:
            status = "not_verified"
        elif cout is None:
            status = "in_progress"
        elif e.planned_minutes and (v.minutes_on_site or 0) < e.planned_minutes * 0.75:
            status = "short"
        else:
            status = "verified"
        yield {
            "service_type": service_type,
            "recipient": household.patient.name,
            "date": e.window_start.astimezone(tz).date().isoformat(),
            "location": household.patient.address,
            "provider": e.caregiver or "",
            "time_in": cin.at.astimezone(tz).strftime("%H:%M") if cin else "",
            "time_out": cout.at.astimezone(tz).strftime("%H:%M") if cout else "",
            "minutes_on_site": round(v.minutes_on_site) if v.minutes_on_site is not None else "",
            "planned_minutes": e.planned_minutes or "",
            "status": status,
            "verification_method": "signed rotating code shown to Ring doorbell camera" if cin else "",
            "evidence": ";".join(p for p in ((cin.evidence_path if cin else None),
                                             (cout.evidence_path if cout else None)) if p),
        }


def to_csv(r: Reconciliation, household: Household) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    for row in rows(r, household):
        w.writerow(row)
    return buf.getvalue()
