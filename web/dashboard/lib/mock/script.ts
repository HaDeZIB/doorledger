// Fixture "day" for mock mode: Rosa Martínez, 81, Tampa FL (fictional).
// Every record is placed on today's date in the household timezone so the demo always
// looks like "today". Scenarios are just windows of demo-clock time over this same day.

import type {
  Action,
  Expectation,
  Finding,
  Household,
  LedgerRecord,
  Observation,
  Scenario,
} from "../types";
import { DEFAULT_TZ, zonedISO } from "../time";

export const MOCK_TZ = DEFAULT_TZ;
export const AMBIENT_C = 34.5;

export const DAY_START = "07:00";
export const DAY_END = "20:00";

export const SCENARIOS: Record<Scenario, { label: string; from: string; to: string; blurb: string }> = {
  porch_heat: {
    label: "Insulin on a hot porch",
    from: "13:05",
    to: "14:36",
    blurb: "Delivery at 1:12 PM, 94°F sun, escalation Rosa → neighbor → family",
  },
  late_short_visit: {
    label: "Late & short visit",
    from: "08:55",
    to: "10:15",
    blurb: "Aide checks in 41 min late and leaves after 27 of 60 min",
  },
  full_day: {
    label: "Full day",
    from: "07:00",
    to: "19:45",
    blurb: "Morning visit, insulin delivery, missed evening visit + backup aide",
  },
};

export const DEFAULT_START = "14:05";
export const RESET_TIME = "07:00";

export function mockHousehold(): Household {
  return {
    id: "hh_rosa_tampa",
    patient: {
      name: "Rosa Martínez",
      age: 81,
      address: "4127 W Bay Vista Ave, Tampa, FL 33611",
      timezone: MOCK_TZ,
    },
    people: [
      { name: "Rosa Martínez", role: "patient", escalation_order: 1 },
      { name: "Luis Ortega", role: "neighbor", escalation_order: 2 },
      { name: "Ana Martínez", role: "family", escalation_order: 3 },
      { name: "BrightPath Home Care", role: "agency", escalation_order: 4 },
      { name: "Maria Gómez", role: "caregiver", escalation_order: 5 },
    ],
    device: { id: "ring_dev_frontdoor_01", name: "Front Door", online: true, source: "replay" },
    ambient: { celsius: AMBIENT_C, source: "open-meteo" },
  };
}

export interface MockDay {
  date: string;
  expectations: Expectation[];
  observations: Observation[];
  findings: Finding[];
  actions: Action[];
  records: LedgerRecord[];
}

export function buildMockDay(date: string): MockDay {
  const t = (hhmm: string) => zonedISO(date, hhmm, MOCK_TZ);
  const dev = "ring_dev_frontdoor_01";
  const compact = date.replaceAll("-", "");

  const expectations: Expectation[] = [
    {
      id: "exp_visit_am",
      kind: "caregiver_visit",
      title: "Morning care visit",
      window_start: t("09:00"),
      window_end: t("10:00"),
      caregiver: "Maria Gómez",
      agency: "BrightPath Home Care",
      planned_minutes: 60,
      visit_id: `BP-${compact}-0412`,
    },
    {
      id: "exp_delivery_insulin",
      kind: "medication_delivery",
      title: "Insulin delivery",
      window_start: t("12:00"),
      window_end: t("16:00"),
      carrier: "CVS Specialty courier",
      tracking: "CVS-SP-88213407",
      medication: { name: "Insulin glargine pens", store_min_c: 2, store_max_c: 8, excursion_max_c: 30 },
    },
    {
      id: "exp_visit_pm",
      kind: "caregiver_visit",
      title: "Evening care visit",
      window_start: t("17:00"),
      window_end: t("18:00"),
      caregiver: "Maria Gómez",
      agency: "BrightPath Home Care",
      planned_minutes: 60,
      visit_id: `BP-${compact}-0413`,
    },
  ];
  const [am, ins, pm] = expectations;

  const O = (o: Omit<Observation, "device_id">): Observation => ({ device_id: dev, ...o });
  const observations: Observation[] = [
    O({ id: "obs_am_vehicle", kind: "vehicle_arrived", at: t("09:39:30"), source: "ring_webhook", confidence: 0.88, detail: { description: "Car parked at curb" } }),
    O({ id: "obs_am_in", kind: "presence_check_in", at: t("09:41:10"), source: "ring_live_view", confidence: 0.99, visit_id: am.visit_id, evidence_path: "mock/presence_check_in.jpg", detail: { caregiver: "Maria Gómez", method: "rotating_code", code_valid: true, distance_cm: 40 } }),
    O({ id: "obs_am_out", kind: "presence_check_out", at: t("10:08:20"), source: "ring_live_view", confidence: 0.98, visit_id: am.visit_id, evidence_path: "mock/presence_check_out.jpg", detail: { caregiver: "Maria Gómez", method: "rotating_code", code_valid: true } }),
    O({ id: "obs_mid_person", kind: "person_at_door", at: t("11:47:05"), source: "ring_snapshot", confidence: 0.91, evidence_path: "mock/person_at_door.jpg", detail: { description: "Adult at door ~2 min, left a flyer", duration_s: 115 } }),
    O({ id: "obs_ins_vehicle", kind: "vehicle_arrived", at: t("13:11:20"), source: "ring_webhook", confidence: 0.9, detail: { description: "White van stopped" } }),
    O({ id: "obs_ins_drop", kind: "package_dropped", at: t("13:12:40"), source: "ring_snapshot", confidence: 0.94, evidence_path: "mock/package_dropped.jpg", detail: { expectation_id: ins.id, description: "Insulated cooler box left by door mat", in_sun: true } }),
    O({ id: "obs_ins_person", kind: "person_at_door", at: t("14:24:30"), source: "ring_live_view", confidence: 0.93, evidence_path: "mock/person_at_door.jpg", detail: { description: "Adult approaches the door" } }),
    O({ id: "obs_ins_removed", kind: "package_removed", at: t("14:26:00"), source: "ring_snapshot", confidence: 0.92, evidence_path: "mock/package_removed.jpg", detail: { expectation_id: ins.id, description: "Box no longer visible on porch" } }),
    O({ id: "obs_pm_vehicle", kind: "vehicle_arrived", at: t("18:04:10"), source: "ring_webhook", confidence: 0.87, detail: { description: "Car parked at curb" } }),
    O({ id: "obs_pm_in", kind: "presence_check_in", at: t("18:06:00"), source: "ring_live_view", confidence: 0.99, visit_id: pm.visit_id, evidence_path: "mock/presence_check_in.jpg", detail: { caregiver: "Keisha Brown", backup: true, method: "rotating_code", code_valid: true } }),
    O({ id: "obs_pm_out", kind: "presence_check_out", at: t("19:01:30"), source: "ring_live_view", confidence: 0.98, visit_id: pm.visit_id, evidence_path: "mock/presence_check_out.jpg", detail: { caregiver: "Keisha Brown", backup: true, method: "rotating_code", code_valid: true } }),
  ];

  const findings: Finding[] = [
    { id: "f_am_late", kind: "late_arrival", severity: "warning", at: t("09:20"), summary: "Maria hasn't checked in yet — 20 min past the 9:00 AM start.", expectation_id: am.id, observation_ids: [], data: { minutes_late: 20 } },
    { id: "f_am_arrived", kind: "late_arrival", severity: "info", at: t("09:41:10"), summary: "Maria checked in at 9:41 AM, 41 min late. Code verified at the Ring doorbell.", expectation_id: am.id, observation_ids: ["obs_am_in"], data: { minutes_late: 41 } },
    { id: "f_am_short", kind: "short_visit", severity: "warning", at: t("10:08:20"), summary: "Morning visit lasted 27 min of the 60 planned (45%).", expectation_id: am.id, observation_ids: ["obs_am_in", "obs_am_out"], data: { minutes_on_site: 27, planned_minutes: 60 } },
    { id: "f_mid_unexpected", kind: "unexpected_activity", severity: "info", at: t("11:49"), summary: "Unscheduled visitor at the door for 2 min. Left a flyer. No action needed.", observation_ids: ["obs_mid_person"], data: {} },
    { id: "f_ins_exposed", kind: "package_exposed", severity: "info", at: t("13:13"), summary: "Insulin left on the porch at 1:12 PM, in direct sun. It's 94°F outside.", expectation_id: ins.id, observation_ids: ["obs_ins_drop"], data: { in_sun: true } },
    { id: "f_ins_risk", kind: "package_at_risk", severity: "warning", at: t("14:16:40"), summary: "Box estimated at 27°C (81°F) — about 20 min until insulin's 30°C (86°F) limit.", expectation_id: ins.id, observation_ids: ["obs_ins_drop"], data: { estimated_internal_c: 27.0 } },
    { id: "f_ins_retrieved", kind: "package_retrieved", severity: "info", at: t("14:26:00"), summary: "Brought inside after 74 min, 9 min after we called neighbor Luis. Estimated 28.7°C peak — under the limit. Close call.", expectation_id: ins.id, observation_ids: ["obs_ins_removed"], data: { minutes_on_porch: 74, estimated_internal_c: 28.7 } },
    { id: "f_pm_late", kind: "late_arrival", severity: "warning", at: t("17:20"), summary: "No check-in for the evening visit — 20 min past the 5:00 PM start.", expectation_id: pm.id, observation_ids: [], data: { minutes_late: 20 } },
    { id: "f_pm_missed", kind: "missed_visit", severity: "critical", at: t("17:45"), summary: "Evening visit missed: no aide at the door 45 min after start. Meal and medication reminder at risk.", expectation_id: pm.id, observation_ids: [], data: {} },
    { id: "f_pm_done", kind: "visit_completed", severity: "info", at: t("19:01:30"), summary: "Backup aide Keisha completed the evening visit: 56 min on site.", expectation_id: pm.id, observation_ids: ["obs_pm_in", "obs_pm_out"], data: { minutes_on_site: 56, planned_minutes: 60 } },
  ];

  const A = (a: Action): Action => a;
  const actions: Action[] = [
    A({ id: "a_am_agency", kind: "notify", target: "BrightPath Home Care", message: "Maria Gómez has not checked in for visit at Rosa Martínez's (scheduled 9:00 AM).", at: t("09:20:30"), finding_id: "f_am_late", delivered: true, data: { channel: "agency_portal" } }),
    A({ id: "a_am_family", kind: "notify", target: "Ana Martínez", message: "Maria is running late for Mom's 9:00 AM visit. We've told BrightPath.", at: t("09:21"), finding_id: "f_am_late", delivered: true, data: { channel: "push" } }),
    A({ id: "a_am_short", kind: "notify", target: "BrightPath Home Care", message: "Visit lasted 27 of 60 min. Flagged for coordinator review before EVV submission.", at: t("10:09"), finding_id: "f_am_short", delivered: true, data: { channel: "agency_portal" } }),
    A({ id: "a_ins_rosa_sms", kind: "notify", target: "Rosa Martínez", message: "Rosa, your insulin from CVS Specialty is at the front door. Please bring it inside and put it in the fridge.", at: t("13:13:30"), finding_id: "f_ins_exposed", delivered: true, data: { channel: "sms" } }),
    A({ id: "a_ins_rosa_call", kind: "notify", target: "Rosa Martínez", message: "Automated call: reminder to bring the insulin box inside.", at: t("13:43"), finding_id: "f_ins_exposed", delivered: false, data: { channel: "voice", status: "no_answer" } }),
    A({ id: "a_ins_luis", kind: "notify", target: "Luis Ortega", message: "Rosa's insulin has been on her porch in the sun for over an hour. Could you bring it inside?", at: t("14:17:10"), finding_id: "f_ins_risk", delivered: true, data: { channel: "voice", status: "answered", reply: "On my way" } }),
    A({ id: "a_ins_ana", kind: "notify", target: "Ana Martínez", message: "Mom's insulin has been outside 65 min. Rosa didn't answer; neighbor Luis is on his way.", at: t("14:17:40"), finding_id: "f_ins_risk", delivered: true, data: { channel: "push" } }),
    A({ id: "a_ins_done", kind: "summary", target: "Ana Martínez", message: "Insulin is inside (74 min on the porch, est. 28.7°C peak). Ask Mom to keep it in the fridge.", at: t("14:26:30"), finding_id: "f_ins_retrieved", delivered: true, data: { channel: "push" } }),
    A({ id: "a_pm_agency", kind: "notify", target: "BrightPath Home Care", message: "No check-in for the 5:00 PM visit at Rosa Martínez's.", at: t("17:20:30"), finding_id: "f_pm_late", delivered: true, data: { channel: "agency_portal" } }),
    A({ id: "a_pm_backup", kind: "request_backup", target: "BrightPath Home Care", message: "Requested a backup aide for Rosa Martínez's evening visit.", at: t("17:45:20"), finding_id: "f_pm_missed", delivered: true, data: { channel: "agency_portal", reply: "Keisha Brown dispatched, ETA 6:05 PM" } }),
    A({ id: "a_pm_family", kind: "notify", target: "Ana Martínez", message: "Mom's evening aide didn't show. BrightPath is sending Keisha, ETA 6:05 PM.", at: t("17:46"), finding_id: "f_pm_missed", delivered: true, data: { channel: "push" } }),
    A({ id: "a_day_evv", kind: "export_evv", target: "BrightPath Home Care", message: "EVV records for 2 visits exported (1 flagged short).", at: t("19:30"), delivered: true, data: { channel: "agency_portal", visits: 2 } }),
    A({ id: "a_day_summary", kind: "summary", target: "Ana Martínez", message: "Today: 2 of 2 visits happened (1 late & short, 1 by backup aide). Insulin delivered and brought in after 74 min.", at: t("19:31"), delivered: true, data: { channel: "email" } }),
  ];

  const records: LedgerRecord[] = [
    ...expectations.map<LedgerRecord>((e) => ({ id: `rec_${e.id}`, kind: "expectation", subtype: e.kind, at: t("06:00"), ref: null, body: e as unknown as Record<string, unknown> })),
    ...observations.map<LedgerRecord>((o) => ({
      id: `rec_${o.id}`,
      kind: "observation",
      subtype: o.kind,
      at: o.at,
      ref: (o.detail.expectation_id as string | undefined) ?? expectations.find((e) => e.visit_id && e.visit_id === o.visit_id)?.id ?? null,
      body: o as unknown as Record<string, unknown>,
    })),
    ...findings.map<LedgerRecord>((f) => ({ id: `rec_${f.id}`, kind: "finding", subtype: f.kind, at: f.at, ref: f.expectation_id ?? null, body: f as unknown as Record<string, unknown> })),
    ...actions.map<LedgerRecord>((a) => ({ id: `rec_${a.id}`, kind: "action", subtype: a.kind, at: a.at, ref: a.finding_id ?? null, body: a as unknown as Record<string, unknown> })),
  ].sort((a, b) => a.at.localeCompare(b.at));

  return { date, expectations, observations, findings, actions, records };
}
