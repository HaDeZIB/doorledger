// Pure helpers shared by live + mock mode: status derivation, labels, EVV CSV.

import type {
  Action,
  DeliveryState,
  EventSource,
  Finding,
  Household,
  LedgerRecord,
  Observation,
  ObservationKind,
  ObservationSource,
  Person,
  RingEvent,
  State,
  VisitState,
} from "./types";
import { dateIn, ms } from "./time";

/** Language of an outbound message ("es" → "ES"), when the backend tells us. */
export function actionLanguage(a: Pick<Action, "data">): string | null {
  const l = a.data?.language;
  return typeof l === "string" && /^[a-z]{2}(-[a-z]{2})?$/i.test(l.trim()) ? l.trim().slice(0, 2).toUpperCase() : null;
}

export const LANGUAGE_NAME: Record<string, string> = { ES: "Spanish", EN: "English" };

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
    const status = visitStatus(v, st.now, st.findings).label;
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
      evvVerificationMethod(v),
      status,
    ];
  });
  return [header, ...rows].map((r) => r.map(esc).join(",")).join("\n") + "\n";
}

/** Camera sources whose frames can prove a signed presence code was shown at the door. */
export const DOOR_CAMERA_SOURCES: readonly ObservationSource[] = ["own_footage", "ring_live_view", "ring_snapshot"];

/**
 * A check-in/out counts as "Verified at the door" ONLY when a camera frame (Ring live view,
 * Ring snapshot, or our own footage) carried a valid signed rotating code: source in
 * DOOR_CAMERA_SOURCES AND detail.method === "signed_code" (set by watcher.py on a valid code).
 * Simulated presence, Ring events without a frame, and any other method never count.
 */
export function isDoorVerified(o: Pick<Observation, "source" | "detail"> | null | undefined): boolean {
  return Boolean(o && DOOR_CAMERA_SOURCES.includes(o.source) && o.detail?.method === "signed_code");
}

export type PresenceProof = "verified" | "simulated" | "unverified" | "none";

export function presenceProof(o: Pick<Observation, "source" | "detail"> | null | undefined): PresenceProof {
  if (!o) return "none";
  if (isDoorVerified(o)) return "verified";
  return o.source === "simulated" ? "simulated" : "unverified";
}

/** EVV "verification method" column: never claims verification for simulated presence. */
export function evvVerificationMethod(v: VisitState): string {
  const pin = presenceProof(v.check_in);
  const pout = presenceProof(v.check_out);
  if (pin === "none") return "";
  if (pin === "verified" && (pout === "verified" || pout === "none")) return `Signed rotating code at Ring doorbell (${SOURCE_LABEL[v.check_in!.source]})`;
  if (pin === "simulated" || pout === "simulated") return "Simulated (demo) - not verified";
  return "Not verified (no signed code in a camera frame)";
}

// Thresholds mirror core/src/doorledger/reconcile.py so derived and backend status agree.
export const LATE_GRACE_MIN = 15;
export const MISSED_AFTER_MIN = 45;
export const SHORT_VISIT_RATIO = 0.75;

// Shared by UI + CSV so status is consistent everywhere.
export type VisitStatusKey = "scheduled" | "awaiting" | "late" | "in_progress" | "completed" | "short" | "missed";
const VISIT_LABEL: Record<VisitStatusKey, string> = {
  scheduled: "Scheduled",
  awaiting: "Awaiting check-in",
  late: "Late",
  in_progress: "In progress",
  completed: "Completed",
  short: "Short visit",
  missed: "Missed",
};
const vs = (key: VisitStatusKey) => ({ key, label: VISIT_LABEL[key] });

/**
 * Visit status. When the backend's findings for this visit are passed in, they win (the
 * reconciler is the source of truth); otherwise we derive with the same thresholds.
 */
export function visitStatus(v: VisitState, nowIso: string, findings?: Finding[]): { key: VisitStatusKey; label: string } {
  const now = ms(nowIso);
  const e = v.expectation;
  const start = ms(e.window_start);
  const end = ms(e.window_end);
  const planned = e.planned_minutes ?? (end - start) / 60000;
  const mine = findings?.filter((f) => f.expectation_id === e.id) ?? [];
  const has = (kind: Finding["kind"], severity?: Finding["severity"]) =>
    mine.some((f) => f.kind === kind && (!severity || f.severity === severity));
  if (v.check_in && v.check_out) {
    if (has("short_visit")) return vs("short");
    if (has("visit_completed")) return vs("completed");
    const mins = v.minutes_on_site ?? 0;
    return vs(planned && mins < planned * SHORT_VISIT_RATIO ? "short" : "completed");
  }
  if (v.check_in) return vs("in_progress");
  if (has("missed_visit")) return vs("missed");
  if (has("late_arrival", "warning")) return vs("late");
  if (now < start) return vs("scheduled");
  if (now - start > MISSED_AFTER_MIN * 60000) return vs("missed");
  if (now - start > LATE_GRACE_MIN * 60000) return vs("late");
  return vs("awaiting");
}

/**
 * The backend records one finding per (expectation, kind, severity), so a late aide yields a
 * "late, not here yet" warning and later an "arrived 22 min late" info. For display we keep
 * only the latest finding per (expectation, kind). Findings without an expectation are kept.
 */
export function latestFindings(findings: Finding[]): Finding[] {
  const latest = new Map<string, Finding>();
  const loose: Finding[] = [];
  for (const f of findings) {
    if (!f.expectation_id) {
      loose.push(f);
      continue;
    }
    const k = `${f.expectation_id}|${f.kind}`;
    const prev = latest.get(k);
    if (!prev || ms(f.at) >= ms(prev.at)) latest.set(k, f);
  }
  return [...latest.values(), ...loose];
}

/** "us.anthropic.claude-haiku-4-5-20251001-v1:0" → "Claude Haiku 4.5"; unknown ids pass through. */
export function modelLabel(id: string | null | undefined): string {
  if (!id) return "";
  const s = id.toLowerCase();
  if (s.startsWith("mock")) return "demo answers (no model)";
  const claude = s.match(/claude-(?:\d-\d-)?(haiku|sonnet|opus)(?:-(\d)(?!\d))?(?:-(\d)(?!\d))?/);
  if (claude) {
    const fam = claude[1][0].toUpperCase() + claude[1].slice(1);
    const ver = claude[2] ? ` ${claude[2]}${claude[3] ? `.${claude[3]}` : ""}` : "";
    return `Claude ${fam}${ver}`;
  }
  const nova = s.match(/nova-(micro|lite|pro|premier)/);
  if (nova) return `Amazon Nova ${nova[1][0].toUpperCase()}${nova[1].slice(1)}`;
  return id;
}

export const SOURCE_LABEL: Record<EventSource, string> = {
  ring_live_view: "Ring live view",
  ring_snapshot: "Ring snapshot",
  ring_webhook: "Ring event",
  ring_history: "Ring history",
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

/** Ring history `event_type` → words ("ding" → "Doorbell pressed"). */
export function ringEventLabel(type: string): string {
  if (type === "ding") return "Doorbell pressed";
  if (type === "on_demand") return "Live view started";
  if (type.startsWith("motion")) {
    const sub = type.split(".")[1];
    return sub && sub !== "motion" ? `Motion (${sub.replaceAll("_", " ")})` : "Motion";
  }
  return type.replaceAll("_", " ");
}

/** Ring history rows from the ledger (kind `ring_event`), oldest first. */
export function ringEvents(timeline: LedgerRecord[]): RingEvent[] {
  return timeline
    .filter((r) => r.kind === "ring_event")
    .map((r) => ({ ...(r.body as unknown as RingEvent), at: (r.body.at as string | null) ?? r.at }))
    .sort((a, b) => ms(a.at!) - ms(b.at!));
}

/** Label that reads right for both the "still late" warning and the "arrived late" info. */
export function findingLabel(f: Pick<Finding, "kind" | "severity">): string {
  if (f.kind === "late_arrival") return f.severity === "info" ? "Arrived late" : "Running late";
  return FINDING_LABEL[f.kind] ?? String(f.kind).replaceAll("_", " ");
}

/** The vision model's one-line description of a frame (Observation.detail.note), if any. */
export function visionNote(o: { detail?: Record<string, unknown> } | null | undefined): string | null {
  const n = o?.detail?.note;
  return typeof n === "string" && n.trim() ? n.trim() : null;
}

/** "us.amazon.nova-2-lite-v1:0" → "Nova 2 Lite". */
export function modelDisplayName(id: string): string {
  const base = id
    .replace(/^(us|eu|apac|global)\./, "")
    .replace(/^[a-z]+\./, "")
    .replace(/-v\d+(:\d+)?$/, "")
    .replace(/-\d{8}$/, "");
  return base
    .split("-")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/**
 * Which model labelled the frame and how long the call took (Observation.detail.vision_model /
 * vision_ms), e.g. "Nova 2 Lite · 1.2 s". Only what the backend recorded: null when the label
 * carries no model (mock fixtures, scripted labels), "recorded" when it was replayed from the
 * vision cache instead of a live call.
 */
export function visionMeta(o: { detail?: Record<string, unknown> } | null | undefined): { text: string; title: string } | null {
  const d = o?.detail;
  const model = d?.vision_model;
  if (typeof model !== "string" || !model) return null;
  const msRaw = d?.vision_ms;
  const parts = [modelDisplayName(model)];
  if (typeof msRaw === "number" && Number.isFinite(msRaw)) parts.push(`${(msRaw / 1000).toFixed(1)} s`);
  const cached = d?.vision_cached === true;
  const reused = d?.vision_reused === true;
  if (cached) parts.push("recorded");
  const title = [
    `Amazon Bedrock ${model}`,
    typeof msRaw === "number" ? `${Math.round(msRaw)} ms for the vision call` : null,
    cached ? "label replayed from the recorded vision cache, not a live call" : null,
    reused ? "scene unchanged, so this frame reused the previous frame's label" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { text: parts.join(" · "), title };
}

export function firstName(name: string): string {
  return name.split(" ")[0];
}

export function personFor(h: Household | null, target: string): Person | undefined {
  return h?.people.find((p) => p.name === target || firstName(p.name) === target);
}

/** "Texted Rosa", "Called Rosa", "Requested backup aide from BrightPath". */
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
    case "cancelled":
      return `${channel === "voice" ? "Call" : channel === "sms" ? "Text" : "Message"} to ${who} not needed`;
    case "notify":
    default:
      if (channel === "sms") return `Texted ${who}`;
      if (channel === "voice") return `${a.data.attempt === 2 ? "Called again" : "Called"} ${who}`;
      if (channel === "agency_portal") return `Alerted ${who}`;
      if (channel === "email") return `Emailed ${who}`;
      if (channel === "telegram" || channel === "whatsapp") return `Messaged ${who}`;
      // there is no DoorLedger app: "app" means the alert was only shown on this dashboard
      if (channel === "app" || channel === "push") return `Dashboard alert for ${who}`;
      return `Notified ${who}`;
  }
}

/**
 * Honest delivery wording. "Sent" = a real gateway (Amazon SNS, Amazon Connect) accepted it;
 * nothing claims the handset received it. "Demo only" = shown on this dashboard, nothing sent
 * (hosted demo, or no gateway configured).
 */
export function actionDeliveryLabel(a: Action): { text: string; tone: "ok" | "warn" | "muted" } {
  const status = String(a.data.status ?? "");
  const reply = a.data.reply ? String(a.data.reply) : "";
  if (a.kind === "cancelled") return { text: "Not needed: Ring saw the pickup", tone: "ok" };
  if (reply) return { text: `Replied: “${reply}”`, tone: "ok" };
  if (status === "answered") return { text: "Answered", tone: "ok" };
  if (status === "no_answer") return { text: "No answer", tone: "warn" };
  if (status === "failed") return { text: "Call failed", tone: "warn" };
  // console notifier / hosted demo: the household's channel (Rosa: call + SMS) was not actually used
  if (a.data.via === "app" && a.data.channel && a.data.channel !== "app") return { text: "Demo only", tone: "muted" };
  if (status === "placed") return { text: "Placed", tone: "ok" };
  if (a.delivered) return { text: "Sent", tone: "ok" };
  return { text: "Pending", tone: "muted" };
}

/**
 * `data.channel` is how the household reaches this person (Rosa: a call + SMS); `data.via` is
 * what actually carried the message in this run. Explains the difference, or null when they match.
 */
export function actionViaNote(a: Action): string | null {
  const via = typeof a.data.via === "string" ? a.data.via : null;
  const channel = String(a.data.channel ?? "");
  if (a.kind === "cancelled") return "The doorbell is the reply: once Ring sees the box picked up, every pending call and text is cancelled.";
  if (a.data.fallback_for === "voice") return "The call could not be placed, so the same words went by SMS.";
  if (channel === "voice" && via === "voice") return "Real call through Amazon Connect, to the one verified demo phone.";
  if (channel === "voice" && via === "app") return "Demo: the call script is shown here. No call was placed.";
  if (!via || via === channel) return null;
  if (via === "app") return "Demo: shown on this dashboard only. Nothing was sent.";
  if (via === "sms") return "Demo: sent as an SMS to the demo phone (Amazon SNS).";
  if (via === "telegram") return "Demo: sent to the demo phone over Telegram.";
  return `Sent via ${via}.`;
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
    const k = visitStatus(v, st.now, st.findings).key;
    return (k === "late" || k === "awaiting" || k === "missed") && now <= ms(v.expectation.window_end) + 30 * 60000;
  });
  if (pending) return pending;
  const soon = sorted.find((v) => ms(v.expectation.window_start) > now && ms(v.expectation.window_start) - now < 60 * 60000);
  if (soon) return soon;
  const past = sorted.filter((v) => ms(v.expectation.window_start) <= now);
  if (past.length) return past[past.length - 1];
  return sorted[0] ?? null;
}

/**
 * Which card leads the "above the fold" hero next to the timeline: the medication card while a
 * package is on the porch, the visit card while a visit needs attention, otherwise whichever of
 * the two had the most recent door event.
 */
export function heroFocus(st: State): "medication" | "visit" {
  const d = featuredDelivery(st);
  const v = featuredVisit(st);
  if (d?.dropped && !d.removed) return "medication";
  if (!v) return "medication";
  if (!d) return "visit";
  const vk = visitStatus(v, st.now, st.findings).key;
  if (vk === "in_progress" || vk === "late" || vk === "awaiting" || vk === "missed") return "visit";
  const dAt = d.removed?.at ?? d.dropped?.at ?? null;
  const vAt = v.check_out?.at ?? v.check_in?.at ?? null;
  if (dAt && (!vAt || ms(dAt) >= ms(vAt))) return "medication";
  if (vAt) return "visit";
  return "medication";
}
