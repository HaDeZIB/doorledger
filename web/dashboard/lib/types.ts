// DoorLedger API contract — keep in sync with API_CONTRACT.md and the FastAPI backend.

export type ISO = string;

export type PersonRole = "patient" | "family" | "neighbor" | "agency" | "caregiver";
export type DeviceSource = "ring_playground" | "ring_api" | "replay";
export type AmbientSource = "open-meteo" | "override" | "fallback";

export interface Person {
  name: string;
  role: PersonRole;
  escalation_order: number;
}

export interface Household {
  id: string;
  patient: { name: string; age: number; address: string; timezone: string };
  people: Person[];
  device: { id: string; name: string; online: boolean | null; source: DeviceSource };
  ambient: { celsius: number; source: AmbientSource };
}

export interface MedicationProfile {
  name: string;
  store_min_c: number;
  store_max_c: number;
  excursion_max_c: number;
}

export type ExpectationKind = "caregiver_visit" | "medication_delivery";

export interface Expectation {
  id: string;
  kind: ExpectationKind;
  title: string;
  window_start: ISO;
  window_end: ISO;
  caregiver?: string;
  agency?: string;
  planned_minutes?: number;
  visit_id?: string;
  carrier?: string;
  tracking?: string;
  medication?: MedicationProfile;
}

export type ObservationKind =
  | "package_dropped"
  | "package_removed"
  | "person_at_door"
  | "vehicle_arrived"
  | "presence_check_in"
  | "presence_check_out";

export type ObservationSource =
  | "ring_live_view"
  | "ring_snapshot"
  | "ring_webhook"
  | "own_footage"
  | "simulated";

export interface Observation {
  id: string;
  kind: ObservationKind;
  at: ISO;
  source: ObservationSource;
  confidence: number;
  device_id?: string;
  visit_id?: string;
  evidence_path?: string;
  detail: Record<string, unknown>;
}

export type FindingKind =
  | "on_time"
  | "late_arrival"
  | "missed_visit"
  | "short_visit"
  | "visit_completed"
  | "package_exposed"
  | "package_at_risk"
  | "package_compromised"
  | "package_retrieved"
  | "delivery_overdue"
  | "unexpected_activity";

export type Severity = "info" | "warning" | "critical";

export interface Finding {
  id: string;
  kind: FindingKind;
  severity: Severity;
  at: ISO;
  summary: string;
  expectation_id?: string;
  observation_ids: string[];
  data: Record<string, unknown>;
}

export type ActionKind = "notify" | "request_backup" | "export_evv" | "summary";

export interface Action {
  id: string;
  kind: ActionKind;
  target: string;
  message: string;
  at: ISO;
  finding_id?: string;
  delivered: boolean;
  data: Record<string, unknown>;
}

export type ExposureStatus = "safe" | "at_risk" | "compromised";

export interface ExposureEstimate {
  minutes_on_porch: number;
  ambient_c: number;
  estimated_internal_c: number;
  minutes_until_excursion_max: number | null;
  status: ExposureStatus;
}

export interface VisitState {
  expectation: Expectation;
  check_in: Observation | null;
  check_out: Observation | null;
  minutes_on_site: number | null;
}

export interface DeliveryState {
  expectation: Expectation;
  dropped: Observation | null;
  removed: Observation | null;
  estimate: ExposureEstimate | null;
}

export interface State {
  now: ISO;
  visits: VisitState[];
  deliveries: DeliveryState[];
  findings: Finding[];
  actions: Action[];
}

export type LedgerKind = "expectation" | "observation" | "finding" | "action";

export interface LedgerRecord {
  id: string;
  kind: LedgerKind;
  subtype: string;
  at: ISO;
  ref: string | null;
  body: Record<string, unknown>;
}

export type Scenario = "porch_heat" | "late_short_visit" | "full_day";

export interface OkResponse {
  ok: boolean;
}
