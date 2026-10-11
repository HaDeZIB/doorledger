// "Right now" banner: ONE pure function from state → sentence. No React, no clock, no units
// context (temperatures go through the `fmt` passed in), so it can be checked against a table
// of cases (lib/banner.cases.ts, run in dev and via `node_modules/.bin/jiti`).
//
// Priority, most urgent first. A lower rule can never claim "all clear" while a higher one
// applies, and the quiet-state wording always acknowledges today's exceptions:
//
//   1. porch        medication on the porch now (exposure estimate)            warn / crit
//   2. compromised  brought inside, but the estimate says it froze / overheated crit
//   3. missed       a visit that never started (until 90 min after its window)  crit
//   4. late         aide past the 15-min grace, not checked in                  warn
//   5. overdue      delivery window ended, nothing left at the door             warn
//   6. in_progress  aide checked in, not out                                    calm
//   7. awaiting     visit window open, still inside the grace period            calm
//   8. short        visit cut short, checked out < 2 h ago                      warn
//   9. retrieved    medication brought inside safely < 60 min ago               ok
//  10. open_window  delivery window open, nothing left yet                      calm
//  11. open_issue   any other unresolved warning / critical finding             warn
//  12. quiet        nothing open; wording depends on today's exceptions         ok / calm
//
// Examples (full table with expectations in lib/banner.cases.ts; mock day, Chicago):
//   09:05  awaiting     "Maria is due now"                       (was: "Everything expected so far has arrived")
//   09:18  late         "Maria is late for the 9:00 AM visit"
//   10:30  short        "Maria's visit was cut short. Agency notified."   (was: "All clear right now")
//   13:30  open_window  "Insulin delivery expected by 5:00 PM"   (was: "Nothing else is scheduled today")
//   14:30  porch        "Rosa's insulin is getting too cold on the porch"
//   14:45  retrieved    "Rosa's insulin is inside"  sub: "…estimated to have stayed above freezing…" (was: "It never froze")
//   16:00  quiet        "Nothing needs attention right now"  sub: "Earlier: Maria's visit was cut short…"

import type { Action, DeliveryState, Finding, Household, State, VisitState } from "./types";
import { firstName, latestFindings, visitStatus } from "./derive";
import { exposureDirection } from "./thermal";
import { fmtDuration, fmtTime, ms } from "./time";

export type BannerTone = "ok" | "calm" | "warn" | "crit";
export type BannerIcon = "check" | "alert" | "user" | "package" | "snow" | "clock";
export type BannerReason =
  | "porch"
  | "compromised"
  | "missed"
  | "late"
  | "overdue"
  | "in_progress"
  | "awaiting"
  | "short"
  | "retrieved"
  | "open_window"
  | "open_issue"
  | "quiet";

export interface Banner {
  reason: BannerReason;
  tone: BannerTone;
  icon: BannerIcon;
  head: string;
  sub: string;
}

/** Temperature formatter, e.g. useUnits().fmt. */
export type TempFmt = (c: number, digits?: number) => string;

const MIN = 60000;
const MISSED_HEADLINE_MIN = 90; // a missed visit leads the banner until 90 min after its window
const SHORT_HEADLINE_MIN = 120; // a short visit leads until 2 h after check-out
const RETRIEVED_HEADLINE_MIN = 60;

export function deriveBanner(state: State, household: Household, fmt: TempFmt): Banner {
  const tz = household.patient.timezone;
  const name = firstName(household.patient.name);
  const now = ms(state.now);
  const t = (iso: string) => fmtTime(iso, tz);
  const findings = latestFindings(state.findings);
  const status = (v: VisitState) => visitStatus(v, state.now, state.findings).key;
  const aide = (v: VisitState) => firstName((v.check_in?.detail.caregiver as string | undefined) ?? v.expectation.caregiver ?? "The aide");
  const what = (d: DeliveryState) => d.expectation.medication?.name.split(" ")[0].toLowerCase() ?? "medication";
  const dirOf = (d: DeliveryState) => exposureDirection(d.estimate, d.expectation.medication, household.ambient.celsius);
  const visits = [...state.visits].sort((a, b) => ms(a.expectation.window_start) - ms(b.expectation.window_start));
  const deliveries = [...state.deliveries].sort((a, b) => ms(a.expectation.window_start) - ms(b.expectation.window_start));

  const earlier = earlierToday(state, household, findings, fmt);
  const next = nextText(state, tz);
  const withEarlier = (s: string) => (earlier.length ? `${s} Earlier: ${earlier.join("; ")}.` : s);

  // 1. porch ---------------------------------------------------------------------------
  const porch = deliveries.find((d) => d.dropped && !d.removed && d.estimate);
  if (porch?.estimate) {
    const e = porch.estimate;
    const cold = dirOf(porch) === "cold";
    const w = what(porch);
    const until = e.minutes_until_excursion_max;
    return {
      reason: "porch",
      tone: e.status === "safe" ? "warn" : "crit",
      icon: cold ? "snow" : "package",
      head:
        e.status === "compromised"
          ? cold
            ? `${name}'s ${w} may have frozen on the porch`
            : `${name}'s ${w} likely got too warm on the porch`
          : e.status === "at_risk"
            ? `${name}'s ${w} is getting too ${cold ? "cold" : "warm"} on the porch`
            : `${name}'s ${w} is on the porch${cold ? ` in ${fmt(e.ambient_c)} cold` : ""}`,
      sub:
        e.status === "compromised"
          ? `Out ${fmtDuration(e.minutes_on_porch)} · est. ${fmt(e.estimated_internal_c)} inside the box.${cold ? " Frozen insulin must be thrown away." : " Call the pharmacy before using it."}`
          : `Out ${fmtDuration(e.minutes_on_porch)} · est. ${fmt(e.estimated_internal_c, 1)} inside the box${
              until !== null ? ` · est. ${cold ? "freezing" : "unsafe"} in ${fmtDuration(until)}` : ""
            }. We're handling it.`,
    };
  }

  // 2. brought inside, but compromised -----------------------------------------------------
  const bad = deliveries.find(
    (d) => d.removed && (d.estimate?.status === "compromised" || findings.some((f) => f.expectation_id === d.expectation.id && f.kind === "package_compromised")),
  );
  if (bad) {
    const cold = dirOf(bad) === "cold";
    const e = bad.estimate;
    return {
      reason: "compromised",
      tone: "crit",
      icon: cold ? "snow" : "alert",
      head: cold ? `${name}'s ${what(bad)} may have frozen. Don't use it` : `${name}'s ${what(bad)} likely got too warm. Don't use it yet`,
      sub: `Brought inside at ${t(bad.removed!.at)}${e ? ` after ${fmtDuration(e.minutes_on_porch)} · est. ${fmt(e.estimated_internal_c)} in the box` : ""}. ${
        cold ? "Frozen insulin must be thrown away; call the pharmacy for a replacement." : "Call the pharmacy before using it."
      }`,
    };
  }

  // 3. missed visit --------------------------------------------------------------------
  const missed = visits.find((v) => status(v) === "missed" && now <= ms(v.expectation.window_end) + MISSED_HEADLINE_MIN * MIN);
  if (missed) {
    return {
      reason: "missed",
      tone: "crit",
      icon: "alert",
      head: `${missed.expectation.title} didn't happen`,
      sub: `No one checked in for the ${t(missed.expectation.window_start)} visit. ${
        hasAction(state, "request_backup") ? "We've asked the agency for a backup aide." : "We're contacting the agency."
      }`,
    };
  }

  // 4. late ----------------------------------------------------------------------------
  const late = visits.find((v) => status(v) === "late");
  if (late) {
    const mins = Math.max(0, Math.round((now - ms(late.expectation.window_start)) / MIN));
    const told = agencyTold(state, household, late.expectation.id);
    return {
      reason: "late",
      tone: "warn",
      icon: "user",
      head: `${aide(late)} is late for the ${t(late.expectation.window_start)} visit`,
      sub: `Not checked in ${mins} min after the start. ${told ? "The agency has been told." : "We're alerting the agency."} We'll update you when she checks in.`,
    };
  }

  // 5. delivery overdue ----------------------------------------------------------------
  const overdue = deliveries.find((d) => !d.dropped && now > ms(d.expectation.window_end));
  if (overdue) {
    const w = what(overdue);
    return {
      reason: "overdue",
      tone: "warn",
      icon: "package",
      head: `${cap(w)} delivery hasn't arrived`,
      sub: withEarlier(`Expected ${t(overdue.expectation.window_start)}–${t(overdue.expectation.window_end)}; the Ring doorbell hasn't seen a drop-off. Check with the pharmacy.`),
    };
  }

  // 6. in progress ---------------------------------------------------------------------
  const inProg = visits.find((v) => status(v) === "in_progress");
  if (inProg) {
    const so = inProg.minutes_on_site ?? Math.max(0, Math.round((now - ms(inProg.check_in!.at)) / MIN));
    return {
      reason: "in_progress",
      tone: "calm",
      icon: "user",
      head: `${aide(inProg)} is with ${name} now`,
      sub: `Checked in at ${t(inProg.check_in!.at)} · ${so} of ${inProg.expectation.planned_minutes ?? "?"} min so far.`,
    };
  }

  // 7. awaiting check-in (window open, inside the grace period) -------------------------
  const awaiting = visits.find((v) => status(v) === "awaiting");
  if (awaiting) {
    return {
      reason: "awaiting",
      tone: "calm",
      icon: "clock",
      head: `${aide(awaiting)} is due now`,
      sub: `Not checked in yet for the ${t(awaiting.expectation.window_start)} visit. We'll tell the agency if she's more than 15 min late.`,
    };
  }

  // 8. visit cut short (recent) ----------------------------------------------------------
  const short = visits.filter((v) => status(v) === "short" && v.check_out && now - ms(v.check_out.at) <= SHORT_HEADLINE_MIN * MIN).pop();
  if (short) {
    const told = agencyTold(state, household, short.expectation.id);
    const open = openDeliveryText(state, tz);
    return {
      reason: "short",
      tone: "warn",
      icon: "user",
      head: `${aide(short)}'s visit was cut short. ${told ? "Agency notified." : "Flagged for the agency."}`,
      sub: `Stayed ${short.minutes_on_site ?? "?"} of ${short.expectation.planned_minutes ?? "?"} planned min (${t(short.check_in!.at)}–${t(short.check_out!.at)}). ${open ?? next}`,
    };
  }

  // 9. medication brought inside safely (recent) ------------------------------------------
  const retrieved = deliveries
    .filter((d) => d.removed && d.estimate && d.estimate.status !== "compromised" && now - ms(d.removed.at) <= RETRIEVED_HEADLINE_MIN * MIN)
    .pop();
  if (retrieved?.estimate) {
    const e = retrieved.estimate;
    const cold = dirOf(retrieved) === "cold";
    return {
      reason: "retrieved",
      tone: "ok",
      icon: "check",
      head: `${name}'s ${what(retrieved)} is inside`,
      sub: `Out ${fmtDuration(e.minutes_on_porch)}; ${cold ? "estimated to have stayed above freezing" : "estimated to have stayed under the unsafe limit"} (est. ${fmt(
        e.estimated_internal_c,
        1,
      )} in the box). It should go in the fridge now.`,
    };
  }

  // 10. a delivery window is open ---------------------------------------------------------
  const open = deliveries.find((d) => !d.dropped && ms(d.expectation.window_start) <= now && now <= ms(d.expectation.window_end));
  if (open) {
    return {
      reason: "open_window",
      tone: "calm",
      icon: "package",
      head: `${cap(what(open))} delivery expected by ${t(open.expectation.window_end)}`,
      sub: withEarlier(`Window opened at ${t(open.expectation.window_start)}; we'll watch the porch and start an exposure clock the moment it's left.`),
    };
  }

  // 11. any other unresolved warning / critical -------------------------------------------
  const unresolved = findings.filter((f) => f.severity !== "info" && !isAccountedFor(f, state, now));
  if (unresolved.length) {
    const f = unresolved.sort((a, b) => ms(b.at) - ms(a.at))[0];
    return {
      reason: "open_issue",
      tone: unresolved.some((x) => x.severity === "critical") ? "crit" : "warn",
      icon: "alert",
      head: unresolved.length > 1 ? `${unresolved.length} issues need a look` : "One issue needs a look",
      sub: `${t(f.at)}: ${f.summary}`,
    };
  }

  // 12. quiet -----------------------------------------------------------------------------
  const anythingDue = [...visits.map((v) => v.expectation), ...deliveries.map((d) => d.expectation)].some((e) => ms(e.window_start) <= now);
  if (earlier.length) {
    return { reason: "quiet", tone: "calm", icon: "check", head: "Nothing needs attention right now", sub: `Earlier: ${earlier.join("; ")}. ${next}` };
  }
  return {
    reason: "quiet",
    tone: "ok",
    icon: "check",
    head: anythingDue ? "Everything expected so far has arrived" : "Nothing due yet today",
    sub: next,
  };
}

// ---------------------------------------------------------------------------------------

function cap(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function hasAction(state: State, kind: Action["kind"]) {
  return state.actions.some((a) => a.kind === kind);
}

/** True when an agency-bound action was sent for a finding on this expectation. */
function agencyTold(state: State, household: Household, expectationId: string): boolean {
  const ids = new Set(state.findings.filter((f) => f.expectation_id === expectationId).map((f) => f.id));
  const agencies = new Set(household.people.filter((p) => p.role === "agency").map((p) => p.name));
  return state.actions.some(
    (a) => a.finding_id && ids.has(a.finding_id) && (a.kind === "request_backup" || agencies.has(a.target) || a.data.channel === "agency_portal"),
  );
}

/** "Next: Insulin refill at 1:00 PM." — only windows that haven't opened yet. */
function nextText(state: State, tz: string): string {
  const now = ms(state.now);
  const upcoming = [...state.visits.map((v) => v.expectation), ...state.deliveries.filter((d) => !d.dropped).map((d) => d.expectation)]
    .filter((e) => ms(e.window_start) > now)
    .sort((a, b) => ms(a.window_start) - ms(b.window_start))[0];
  return upcoming ? `Next: ${upcoming.title} at ${fmtTime(upcoming.window_start, tz)}.` : "Nothing else is scheduled today.";
}

/** "Insulin delivery window is open until 5:00 PM." while a delivery window is open. */
function openDeliveryText(state: State, tz: string): string | null {
  const now = ms(state.now);
  const d = state.deliveries.find((x) => !x.dropped && ms(x.expectation.window_start) <= now && now <= ms(x.expectation.window_end));
  if (!d) return null;
  const w = d.expectation.medication?.name.split(" ")[0] ?? "Delivery";
  return `${cap(w.toLowerCase())} delivery window is open until ${fmtTime(d.expectation.window_end, tz)}.`;
}

/** Findings that a banner rule above already covers (or that were resolved by later events). */
function isAccountedFor(f: Finding, state: State, now: number): boolean {
  const v = state.visits.find((x) => x.expectation.id === f.expectation_id);
  const d = state.deliveries.find((x) => x.expectation.id === f.expectation_id);
  switch (f.kind) {
    case "late_arrival":
      return Boolean(v?.check_in); // she arrived
    case "missed_visit":
    case "short_visit":
      return Boolean(v); // acknowledged in "earlier today"
    case "package_exposed":
    case "package_at_risk":
    case "package_compromised":
      return Boolean(d?.removed); // inside (a compromised one is rule 2)
    case "delivery_overdue":
      return Boolean(d?.dropped);
    case "unexpected_activity":
      return now - ms(f.at) > 60 * MIN; // stale after an hour
    default:
      return false;
  }
}

/** Today's exceptions that are over but must still be acknowledged (never "all clear" over them). */
function earlierToday(state: State, household: Household, findings: Finding[], fmt: TempFmt): string[] {
  const now = ms(state.now);
  const out: string[] = [];
  for (const v of state.visits) {
    const k = visitStatus(v, state.now, state.findings).key;
    const who = firstName((v.check_in?.detail.caregiver as string | undefined) ?? v.expectation.caregiver ?? "The aide");
    if (k === "short" && v.check_out) {
      const told = agencyTold(state, household, v.expectation.id);
      out.push(`${who}'s visit was cut short (${v.minutes_on_site ?? "?"} of ${v.expectation.planned_minutes ?? "?"} min), ${told ? "agency notified" : "flagged for the agency"}`);
    } else if (k === "missed" && now > ms(v.expectation.window_end) + MISSED_HEADLINE_MIN * MIN) {
      const told = state.actions.some((a) => a.kind === "request_backup") ? "backup requested" : agencyTold(state, household, v.expectation.id) ? "agency notified" : "flagged for the agency";
      out.push(`${v.expectation.title} didn't happen, ${told}`);
    } else if (k === "completed" && v.check_in) {
      const lateMin = Math.round((ms(v.check_in.at) - ms(v.expectation.window_start)) / MIN);
      if (lateMin > 15) out.push(`${who} arrived ${lateMin} min late`);
    }
  }
  for (const d of state.deliveries) {
    if (!d.removed || !d.estimate || d.estimate.status === "compromised") continue;
    const hadRisk = findings.some((f) => f.expectation_id === d.expectation.id && f.kind === "package_at_risk");
    if (!hadRisk) continue;
    const w = (d.expectation.medication?.name.split(" ")[0] ?? "medication").toLowerCase();
    const cold = exposureDirection(d.estimate, d.expectation.medication, household.ambient.celsius) === "cold";
    out.push(
      `${w} brought in after ${fmtDuration(d.estimate.minutes_on_porch)}, ${cold ? "est. stayed above freezing" : "est. under the limit"} (${fmt(d.estimate.estimated_internal_c, 1)})`,
    );
  }
  return out;
}
