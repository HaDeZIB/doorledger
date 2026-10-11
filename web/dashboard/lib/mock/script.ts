// Fixture "day" for mock mode: Rosa Martínez, 81, Chicago IL (fictional), a winter day.
// Mirrors the backend demo scenarios in core/src/doorledger/scenarios.py: the Ring Developer
// Playground "Package" clip is a snowy doorstep, so the porch story is insulin left out at
// −9 °C, where the danger is FREEZING (frozen insulin must be thrown away).
//
// Every record is placed on today's date in the household timezone so the demo always looks
// like "today". Scenarios are just windows of demo-clock time over this same day.
//
// Provenance is honest: vehicle + package drop come from Ring Playground footage
// (ring_live_view). Scenes whose real footage hasn't been filmed yet (aide check-in/out,
// package pickup) are `simulated` and carry no evidence_path.

import type {
  Action,
  Expectation,
  Finding,
  Household,
  LedgerRecord,
  Observation,
  Scenario,
} from "../types";
import { DEFAULT_TZ, minuteOfDay, zonedISO } from "../time";

export const MOCK_TZ = DEFAULT_TZ; // America/Chicago
export const AMBIENT_MORNING_C = -6;
export const AMBIENT_AFTERNOON_C = -9;

/** Outside temperature over the demo day: −6 °C in the morning, −9 °C by early afternoon. */
export function mockAmbientAt(iso: string): number {
  const m = minuteOfDay(iso, MOCK_TZ);
  const a = 11 * 60;
  const b = 13 * 60;
  if (m <= a) return AMBIENT_MORNING_C;
  if (m >= b) return AMBIENT_AFTERNOON_C;
  return Math.round((AMBIENT_MORNING_C + ((m - a) / (b - a)) * (AMBIENT_AFTERNOON_C - AMBIENT_MORNING_C)) * 10) / 10;
}

export const SCENARIOS: Record<Scenario, { label: string; from: string; to: string; blurb: string }> = {
  porch_cold: {
    label: "Insulin on a freezing porch",
    from: "13:55",
    to: "14:55",
    blurb: "Ring sees the package at 2:07 PM, 16°F outside · Rosa → neighbor Luis → Ana · inside at 2:40 PM",
  },
  late_short_visit: {
    label: "Late & short visit",
    from: "08:50",
    to: "10:20",
    blurb: "Maria checks in 22 min late and leaves after 43 of 120 min, at 21°F",
  },
  full_day: {
    label: "Full day",
    from: "08:50",
    to: "14:55",
    blurb: "Late & short morning visit, then insulin on a freezing porch",
  },
};

export const DEFAULT_START = "14:20";
export const RESET_TIME = "08:30";

export function mockHousehold(): Household {
  return {
    id: "hh_rosa",
    patient: {
      name: "Rosa Martínez",
      age: 81,
      address: "Chicago, IL",
      timezone: MOCK_TZ,
    },
    people: [
      { name: "Rosa Martínez", role: "patient", escalation_order: 1 },
      { name: "Luis Ortega", role: "neighbor", escalation_order: 2 },
      { name: "Ana Martínez", role: "family", escalation_order: 3 },
      { name: "BrightPath Home Care", role: "agency", escalation_order: 10 },
      { name: "Maria Gómez", role: "caregiver", escalation_order: 20 },
    ],
    device: { id: "ring_dev_frontdoor_01", name: "Front Door", online: true, source: "replay" },
    ambient: { celsius: AMBIENT_AFTERNOON_C, source: "open-meteo" },
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
      title: "Morning personal care",
      window_start: t("09:00"),
      window_end: t("11:00"),
      caregiver: "Maria Gómez",
      agency: "BrightPath Home Care",
      planned_minutes: 120,
      visit_id: `BP-${compact}-0412`,
    },
    {
      id: "exp_delivery_insulin",
      kind: "medication_delivery",
      title: "Insulin refill (CVS Specialty)",
      window_start: t("13:00"),
      window_end: t("17:00"),
      carrier: "UPS",
      tracking: "1Z-DEMO-4471",
      medication: { name: "Insulin glargine pens", store_min_c: 2, store_max_c: 8, excursion_max_c: 30, freeze_c: 0 },
    },
  ];
  const [am, ins] = expectations;

  const O = (o: Omit<Observation, "device_id">): Observation => ({ device_id: dev, ...o });
  const observations: Observation[] = [
    // Morning visit: our own footage of the aide's code isn't filmed yet → simulated, no frame.
    O({ id: "obs_am_in", kind: "presence_check_in", at: t("09:22"), source: "simulated", confidence: 1, visit_id: am.visit_id, detail: { caregiver: "Maria Gómez", method: "compact_qr" } }),
    O({ id: "obs_am_out", kind: "presence_check_out", at: t("10:05"), source: "simulated", confidence: 1, visit_id: am.visit_id, detail: { caregiver: "Maria Gómez", method: "compact_qr" } }),
    // Afternoon: Ring Developer Playground footage (snowy doorstep).
    O({ id: "obs_ins_vehicle", kind: "vehicle_arrived", at: t("14:05"), source: "ring_live_view", confidence: 0.9, evidence_path: "evidence/vehicle.jpg", detail: { description: "Delivery van in front of the house", note: "vehicle in front of the house" } }),
    O({ id: "obs_ins_drop", kind: "package_dropped", at: t("14:07"), source: "ring_live_view", confidence: 0.94, evidence_path: "evidence/package.jpg", detail: { expectation_id: ins.id, description: "Package left on the snowy doorstep", note: "parcel on the doorstep", in_sun: false } }),
    // Pickup footage not filmed yet → simulated, no frame.
    O({ id: "obs_ins_removed", kind: "package_removed", at: t("14:40"), source: "simulated", confidence: 1, detail: { expectation_id: ins.id, description: "Neighbor picked it up and took it inside" } }),
  ];

  const findings: Finding[] = [
    { id: "f_am_late", kind: "late_arrival", severity: "warning", at: t("09:16"), summary: "Maria hasn't checked in yet, 16 min past the 9:00 AM start.", expectation_id: am.id, observation_ids: [], data: { minutes_late: 16 } },
    { id: "f_am_arrived", kind: "late_arrival", severity: "info", at: t("09:22"), summary: "Maria checked in at 9:22 AM, 22 min late.", expectation_id: am.id, observation_ids: ["obs_am_in"], data: { late_minutes: 22 } },
    { id: "f_am_short", kind: "short_visit", severity: "warning", at: t("10:05"), summary: "Maria stayed 43 of the 120 planned minutes (36%). It's 21°F (−6°C) outside.", expectation_id: am.id, observation_ids: ["obs_am_in", "obs_am_out"], data: { minutes_on_site: 43, planned_minutes: 120 } },
    { id: "f_ins_exposed", kind: "package_exposed", severity: "info", at: t("14:07"), summary: "Ring saw the insulin left on the porch at 2:07 PM. It's 16°F (−9°C) outside, so it could freeze.", expectation_id: ins.id, observation_ids: ["obs_ins_drop"], data: { ambient_c: -9, direction: "cold", unsafe_c: 0 } },
    { id: "f_ins_risk", kind: "package_at_risk", severity: "warning", at: t("14:27"), summary: "Getting too cold: box estimated at 36°F (2.2°C), about 20 min from freezing at 32°F (0°C). Rosa hasn't brought it in.", expectation_id: ins.id, observation_ids: ["obs_ins_drop"], data: { estimated_internal_c: 2.2, minutes_until_excursion_max: 19.8, direction: "cold", unsafe_c: 0 } },
    { id: "f_ins_retrieved", kind: "package_retrieved", severity: "info", at: t("14:40"), summary: "Brought inside after 33 min, 3 min after we messaged Ana. Estimated 33°F (0.7°C) inside the box: it never froze. Close call.", expectation_id: ins.id, observation_ids: ["obs_ins_drop", "obs_ins_removed"], data: { minutes_on_porch: 33, estimated_internal_c: 0.7, direction: "cold", unsafe_c: 0 } },
  ];

  const A = (a: Action): Action => a;
  const actions: Action[] = [
    A({ id: "a_am_agency", kind: "notify", target: "BrightPath Home Care", message: "Maria hasn't checked in for Rosa Martínez's 9:00 AM visit. Can you confirm an ETA?", at: t("09:16:30"), finding_id: "f_am_late", delivered: true, data: { channel: "agency_portal", language: "en" } }),
    A({ id: "a_am_family", kind: "notify", target: "Ana Martínez", message: "Maria stayed 43 of 120 planned minutes at Mom's this morning. The visit record has been flagged for review.", at: t("10:05:30"), finding_id: "f_am_short", delivered: true, data: { channel: "push", language: "en" } }),
    A({ id: "a_am_short", kind: "notify", target: "BrightPath Home Care", message: "Morning visit at Rosa Martínez's lasted 43 of 120 min. Flagged for coordinator review before EVV submission.", at: t("10:06"), finding_id: "f_am_short", delivered: true, data: { channel: "agency_portal", language: "en" } }),
    A({ id: "a_ins_rosa", kind: "notify", target: "Rosa Martínez", message: "Hola Rosa, le dejaron su insulina en la puerta y afuera está helando (−9 °C). Por favor métala a la casa y guárdela en el refrigerador.", at: t("14:07:30"), finding_id: "f_ins_exposed", delivered: true, data: { channel: "sms", language: "es" } }),
    A({ id: "a_ins_luis", kind: "notify", target: "Luis Ortega", message: "Hi Luis, Rosa's insulin has been on her porch for 20 min in the freezing cold and she hasn't picked it up. Could you bring it inside for her?", at: t("14:27:20"), finding_id: "f_ins_risk", delivered: true, data: { channel: "sms", language: "en" } }),
    A({ id: "a_ins_ana", kind: "notify", target: "Ana Martínez", message: "Mom's insulin has been outside 30 min in the freezing cold and nobody nearby has brought it in yet. Could you call her or someone close by?", at: t("14:37"), finding_id: "f_ins_risk", delivered: true, data: { channel: "push", language: "en" } }),
    A({ id: "a_ins_done", kind: "notify", target: "Ana Martínez", message: "Good news: Mom's insulin was brought inside after 33 min (est. 33°F / 0.7°C in the box). It never froze. Ask her to put it in the fridge.", at: t("14:40:20"), finding_id: "f_ins_retrieved", delivered: true, data: { channel: "push", language: "en" } }),
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
