// Pure helpers shared by live + mock mode: status derivation, labels, EVV CSV.

import type {
  Action,
  DeliveryState,
  Finding,
  Household,
  ObservationKind,
  ObservationSource,
  Person,
  State,
  VisitState,
} from "./types";
import { dateIn, ms } from "./time";

/** Builds the EVV CSV (21st Century Cures Act §12006 six data elements + status). */
export function evvCsvFromState(st: State, patient: string, address: string, tz: string): string {
  const header = [
    "visit_id",
    "service_type",
    "individual_receiving_service",
    "date",
    "location",
    "individual_providing_service",
    "time_in",
    "time_out",
    "minutes_on_site",
    "planned_minutes",
    "verification_method",
    "status",
  ];
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const rows = st.visits.map((v) => {
    const e = v.expectation;
    const provider = (v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver ?? "";
    const status = visitStatus(v, st.now).label;
    return [
      e.visit_id ?? e.id,
      "Personal care (T1019)",
      patient,
      dateIn(e.window_start, tz),
      address,
      provider,
      v.check_in?.at ?? "",
      v.check_out?.at ?? "",
      v.minutes_on_site ?? "",
      e.planned_minutes ?? "",
      v.check_in ? "Rotating presence code at Ring doorbell" : "",
      status,
    ];
  });
  return [header, ...rows].map((r) => r.map(esc).join(",")).join("\n") + "\n";
}

// Shared by UI + CSV so status is consistent everywhere.
export type VisitStatusKey = "scheduled" | "awaiting" | "late" | "in_progress" | "completed" | "short" | "missed";
export function visitStatus(v: VisitState, nowIso: string): { key: VisitStatusKey; label: string } {
  const now = ms(nowIso);
  const e = v.expectation;
  const start = ms(e.window_start);
  const end = ms(e.window_end);
  const planned = e.planned_minutes ?? (end - start) / 60000;
  if (v.check_in && v.check_out) {
    const mins = v.minutes_on_site ?? 0;
    if (mins < planned * 0.75) return { key: "short", label: "Short visit" };
    return { key: "completed", label: "Completed" };
  }
  if (v.check_in) return { key: "in_progress", label: "In progress" };
  if (now < start) return { key: "scheduled", label: "Scheduled" };
  if (now - start > 30 * 60000 || now > end) return { key: "missed", label: "Missed" };
  if (now - start > 15 * 60000) return { key: "late", label: "Late" };
  return { key: "awaiting", label: "Awaiting check-in" };
}


export const SOURCE_LABEL: Record<ObservationSource, string> = {
  ring_live_view: "Ring live view",
  ring_snapshot: "Ring snapshot",
  ring_webhook: "Ring event",
  own_footage: "Own footage",
  simulated: "Simulated",
};

export const OBS_LABEL: Record<ObservationKind, string> = {
  package_dropped: "Package left at door",
  package_removed: "Package taken inside",
  person_at_door: "Person at door",
  vehicle_arrived: "Vehicle arrived",
  presence_check_in: "Aide checked in",
  presence_check_out: "Aide checked out",
};

export const FINDING_LABEL: Record<Finding["kind"], string> = {
  on_time: "On time",
  late_arrival: "Late arrival",
  missed_visit: "Missed visit",
  short_visit: "Short visit",
  visit_completed: "Visit completed",
  package_exposed: "Package outside",
  package_at_risk: "Medication at risk",
  package_compromised: "Medication compromised",
  package_retrieved: "Brought inside",
  delivery_overdue: "Delivery overdue",
  unexpected_activity: "Unscheduled activity",
};

export function firstName(name: string): string {
  return name.split(" ")[0];
}

export function personFor(h: Household | null, target: string): Person | undefined {
  return h?.people.find((p) => p.name === target || firstName(p.name) === target);
}

/** "Texted Rosa", "Called neighbor Luis", "Requested backup aide from BrightPath". */
export function actionHeadline(a: Action, h: Household | null): string {
  const p = personFor(h, a.target);
  const channel = String(a.data.channel ?? "");
  let who = p ? firstName(p.name) : a.target;
  if (p?.role === "neighbor") who = `neighbor ${firstName(p.name)}`;
  if (p?.role === "family") who = `${firstName(p.name)} (family)`;
  if (p?.role === "agency") who = p.name.replace(/ Home Care$/, "");
  switch (a.kind) {
    case "request_backup":
      return `Requested backup aide from ${who}`;
    case "export_evv":
      return `Exported EVV records to ${who}`;
    case "summary":
      return channel === "email" ? `Emailed daily summary to ${who}` : `Sent update to ${who}`;
    case "notify":
    default:
      if (channel === "sms") return `Texted ${who}`;
      if (channel === "voice") return `Called ${who}`;
      if (channel === "agency_portal") return `Alerted ${who}`;
      if (channel === "email") return `Emailed ${who}`;
      return `Notified ${who}`;
  }
}

export function actionDeliveryLabel(a: Action): { text: string; tone: "ok" | "warn" | "muted" } {
  const status = String(a.data.status ?? "");
  const reply = a.data.reply ? String(a.data.reply) : "";
  if (reply) return { text: `Replied: “${reply}”`, tone: "ok" };
  if (status === "no_answer") return { text: "No answer", tone: "warn" };
  if (a.delivered) return { text: "Delivered", tone: "ok" };
  return { text: "Pending", tone: "muted" };
}

/** Escalation chain for porch alerts: patient → neighbor → family, by escalation_order. */
export function escalationChain(h: Household | null): Person[] {
  if (!h) return [];
  return h.people
    .filter((p) => p.role === "patient" || p.role === "neighbor" || p.role === "family")
    .sort((a, b) => a.escalation_order - b.escalation_order);
}

export function findingsFor(st: State, expectationId: string): Finding[] {
  return st.findings.filter((f) => f.expectation_id === expectationId);
}

export function actionsForFindings(st: State, findings: Finding[]): Action[] {
  const ids = new Set(findings.map((f) => f.id));
  return st.actions.filter((a) => a.finding_id && ids.has(a.finding_id));
}

/** Which delivery to feature: on the porch now > most recent dropped > next expected. */
export function featuredDelivery(st: State): DeliveryState | null {
  const onPorch = st.deliveries.find((d) => d.dropped && !d.removed);
  if (onPorch) return onPorch;
  const done = [...st.deliveries].filter((d) => d.dropped).sort((a, b) => ms(b.dropped!.at) - ms(a.dropped!.at));
  if (done.length) return done[0];
  return [...st.deliveries].sort((a, b) => ms(a.expectation.window_start) - ms(b.expectation.window_start))[0] ?? null;
}

/** Which visit to feature: in progress > late/awaiting > upcoming within 60 min > latest past > next. */
export function featuredVisit(st: State): VisitState | null {
  const now = ms(st.now);
  const sorted = [...st.visits].sort((a, b) => ms(a.expectation.window_start) - ms(b.expectation.window_start));
  const inProg = sorted.find((v) => v.check_in && !v.check_out);
  if (inProg) return inProg;
  const pending = sorted.find((v) => {
    const k = visitStatus(v, st.now).key;
    return (k === "late" || k === "awaiting" || k === "missed") && now <= ms(v.expectation.window_end) + 30 * 60000;
  });
  if (pending) return pending;
  const soon = sorted.find((v) => ms(v.expectation.window_start) > now && ms(v.expectation.window_start) - now < 60 * 60000);
  if (soon) return soon;
  const past = sorted.filter((v) => ms(v.expectation.window_start) <= now);
  if (past.length) return past[past.length - 1];
  return sorted[0] ?? null;
}
