// DoorLedger API contract — keep in sync with API_CONTRACT.md and the FastAPI backend.

export type ISO = string;

export type PersonRole = "patient" | "family" | "neighbor" | "agency" | "caregiver";
export type DeviceSource = "ring_playground" | "ring_api" | "replay";
/** "scenario" = the hosted demo's scripted weather (mock mode), never a live source. */
export type AmbientSource = "open-meteo" | "override" | "fallback" | "scenario";

/** How the household chose to reach a person (backend `Person.channel`). Rosa uses no app: a voice call + SMS. */
export type PersonChannel = "sms" | "push" | "voice" | "email" | "agency_portal";

export interface Person {
  name: string;
  role: PersonRole;
  escalation_order: number;
  language?: string;
  channel?: PersonChannel | null;
  /** Every channel used for one contact, primary first (Rosa: ["voice", "sms"], sent together). */
  channels?: PersonChannel[];
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
  /** Insulin that has frozen must be discarded. Backend default 0.0. */
  freeze_c?: number;
  max_minutes_above_store?: number | null;
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

/** Provenance badges also cover raw Ring history rows (ledger kind `ring_event`). */
export type EventSource = ObservationSource | "ring_history";

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

/** "cancelled": a pending step that no longer happens because Ring saw the box picked up. */
export type ActionKind = "notify" | "request_backup" | "export_evv" | "summary" | "cancelled";

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
/** Which limit the box is drifting toward: "hot" = excursion_max_c, "cold" = freeze_c. */
export type ExposureDirection = "hot" | "cold" | null;

export interface ExposureEstimate {
  minutes_on_porch: number;
  ambient_c: number;
  estimated_internal_c: number;
  /** Minutes until the RELEVANT limit (freezing when direction is cold, excursion_max when hot). */
  minutes_until_excursion_max: number | null;
  status: ExposureStatus;
  direction?: ExposureDirection;
  /** The limit being approached: 0.0 for cold, 30.0 (excursion_max_c) for hot, null otherwise. */
  unsafe_c?: number | null;
  minutes_above_store_max?: number;
  minutes_until_store_max?: number | null;
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

export type LedgerKind = "expectation" | "observation" | "finding" | "action" | "ring_event";

/**
 * Body of a `ring_event` ledger record: a Ring history row (GET /v1/history/devices/{id}/events)
 * that the live poller acted on. Only written with a live Ring token; never in mock/replay demos.
 */
export interface RingEvent {
  id: string;
  event_type: "ding" | "on_demand" | "motion" | string;
  at: ISO | null;
  end?: ISO | null;
  device_id?: string | null;
  source: "ring_history";
  /** What DoorLedger did about it: "watch" or "burst watch" (doorbell press). */
  action?: string;
}

export interface LedgerRecord {
  id: string;
  kind: LedgerKind;
  subtype: string;
  at: ISO;
  ref: string | null;
  body: Record<string, unknown>;
}

/** `porch_heat` is still accepted by the backend as an alias of `porch_cold`. */
export type Scenario = "porch_cold" | "porch_early_pickup" | "late_short_visit" | "full_day";

export interface OkResponse {
  ok: boolean;
}

// ----- CareAgent (Bedrock) ------------------------------------------------------------

export interface ToolCall {
  name: string;
  input: Record<string, unknown>;
}

export interface AgentUsage {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  [k: string]: unknown;
}

/** POST /api/ask → 200; 503 when no Bedrock model is available. */
export interface AskResponse {
  answer: string;
  tool_calls: ToolCall[];
  model: string;
  latency_ms: number;
  usage: AgentUsage | null;
}

/** GET /api/summary */
export interface SummaryResponse {
  summary: string;
  tool_calls: ToolCall[];
  model: string;
  latency_ms: number;
  usage: AgentUsage | null;
}
