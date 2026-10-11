// Typed table of "Right now" banner cases, checked against deriveBanner().
//
//  - In `next dev` the dashboard runs them once on load and logs the result to the console
//    ("[banner] 18/18 cases pass" or a console.error per failure). Never bundled for production.
//  - Headless:  node_modules/.bin/jiti lib/banner.cases.ts
//
// States come from the mock fixture day (the same one the demo plays), optionally mutated to
// reach states the fixture never shows (missed visit, overdue or compromised delivery).

import type { State } from "./types";
import { deriveBanner, type Banner, type BannerReason, type BannerTone, type TempFmt } from "./banner";
import { mockStateAt } from "./mock/engine";
import { MOCK_TZ, mockHousehold } from "./mock/script";
import { ms, zonedISO } from "./time";

const DATE = "2026-01-15"; // a winter weekday; any date works
const fmtC: TempFmt = (c, digits = 0) => `${c.toFixed(digits)}°C`;

interface Case {
  name: string;
  at: string; // HH:MM in the household timezone
  mutate?: (s: State) => State;
  expect: {
    reason: BannerReason;
    tone?: BannerTone;
    head?: string[]; // substrings the headline must contain
    sub?: string[]; // substrings the sub line must contain
    never?: string[]; // substrings neither line may contain
  };
}

const ALL_CLEAR = ["All clear", "Everything expected so far has arrived", "never froze"];

/** No one ever checked in for the morning visit. */
const noShow = (s: State): State => ({
  ...s,
  visits: s.visits.map((v) => ({ ...v, check_in: null, check_out: null, minutes_on_site: null })),
  findings: s.findings.filter((f) => f.expectation_id !== "exp_visit_am"),
  actions: s.actions.filter((a) => !["f_am_late", "f_am_arrived", "f_am_short"].includes(a.finding_id ?? "")),
});
/** The insulin was never dropped off. */
const noDrop = (s: State): State => ({
  ...s,
  deliveries: s.deliveries.map((d) => ({ ...d, dropped: null, removed: null, estimate: null })),
  findings: s.findings.filter((f) => f.expectation_id !== "exp_delivery_insulin"),
});
/** It came inside, but the estimate says it froze. */
const frozen = (s: State): State => ({
  ...s,
  deliveries: s.deliveries.map((d) => (d.estimate ? { ...d, estimate: { ...d.estimate, status: "compromised", estimated_internal_c: -0.6 } } : d)),
});

export const BANNER_CASES: Case[] = [
  { name: "before anything is due", at: "08:40", expect: { reason: "quiet", tone: "ok", head: ["Nothing due yet"], sub: ["Next: Morning personal care at 9:00 AM"] } },
  // review-02: "Everything expected so far has arrived" while Maria was not checked in
  { name: "aide due, inside grace period", at: "09:05", expect: { reason: "awaiting", head: ["Maria is due now"], never: ALL_CLEAR } },
  { name: "aide late", at: "09:18", expect: { reason: "late", tone: "warn", head: ["Maria is late for the 9:00 AM visit"], sub: ["agency has been told"], never: ALL_CLEAR } },
  { name: "aide on site", at: "09:40", expect: { reason: "in_progress", head: ["Maria is with Rosa now"] } },
  // review-02: "All clear" after a visit cut short by 77 min
  { name: "right after a short visit", at: "10:30", expect: { reason: "short", tone: "warn", head: ["cut short", "Agency notified"], sub: ["43 of 120"], never: ALL_CLEAR } },
  { name: "hours after a short visit", at: "12:30", expect: { reason: "quiet", tone: "calm", head: ["Nothing needs attention"], sub: ["Earlier:", "cut short", "Next: Insulin refill"], never: ALL_CLEAR } },
  // review-02: "Nothing else is scheduled today" inside the insulin window
  {
    name: "delivery window open",
    at: "13:30",
    expect: { reason: "open_window", head: ["Insulin delivery expected by 5:00 PM"], sub: ["watch the porch", "cut short"], never: ["Nothing else is scheduled", ...ALL_CLEAR] },
  },
  { name: "package just dropped", at: "14:10", expect: { reason: "porch", tone: "warn", head: ["insulin is on the porch"], sub: ["est."] } },
  { name: "package getting too cold", at: "14:30", expect: { reason: "porch", tone: "crit", head: ["getting too cold"], sub: ["est.", "freezing in"] } },
  // review-02: "Inside. It never froze." stated a model estimate as fact
  { name: "brought inside in time", at: "14:45", expect: { reason: "retrieved", tone: "ok", head: ["insulin is inside"], sub: ["estimated to have stayed above freezing", "est."], never: ["never froze"] } },
  {
    name: "late afternoon, all done",
    at: "16:00",
    expect: { reason: "quiet", tone: "calm", sub: ["Earlier:", "cut short", "est. stayed above freezing", "Nothing else is scheduled today"], never: ALL_CLEAR },
  },
  // states the fixture day never reaches
  { name: "no-show, 50 min in", at: "09:50", mutate: noShow, expect: { reason: "missed", tone: "crit", head: ["didn't happen"], never: ALL_CLEAR } },
  {
    name: "no-show, delivery window open later",
    at: "13:30",
    mutate: noShow,
    expect: { reason: "open_window", sub: ["Earlier:", "didn't happen"], never: ["Nothing else is scheduled", ...ALL_CLEAR] },
  },
  { name: "no-show, evening", at: "18:00", mutate: (s) => noDrop(noShow(s)), expect: { reason: "overdue", tone: "warn", never: ALL_CLEAR } },
  { name: "delivery overdue", at: "17:30", mutate: noDrop, expect: { reason: "overdue", tone: "warn", head: ["hasn't arrived"], never: ALL_CLEAR } },
  { name: "brought in but frozen", at: "14:45", mutate: frozen, expect: { reason: "compromised", tone: "crit", head: ["may have frozen"], sub: ["est.", "thrown away"], never: ALL_CLEAR } },
  { name: "frozen, hours later", at: "17:30", mutate: frozen, expect: { reason: "compromised", tone: "crit" } },
];

export interface CaseResult {
  name: string;
  ok: boolean;
  problems: string[];
  got: Banner;
}

export function runBannerCases(): CaseResult[] {
  const household = mockHousehold();
  return BANNER_CASES.map((c) => {
    const base = mockStateAt(DATE, ms(zonedISO(DATE, c.at, MOCK_TZ)));
    const got = deriveBanner(c.mutate ? c.mutate(base) : base, household, fmtC);
    const problems: string[] = [];
    const e = c.expect;
    if (got.reason !== e.reason) problems.push(`reason ${got.reason} ≠ ${e.reason}`);
    if (e.tone && got.tone !== e.tone) problems.push(`tone ${got.tone} ≠ ${e.tone}`);
    for (const s of e.head ?? []) if (!got.head.includes(s)) problems.push(`head lacks "${s}"`);
    for (const s of e.sub ?? []) if (!got.sub.includes(s)) problems.push(`sub lacks "${s}"`);
    for (const s of e.never ?? []) if (got.head.includes(s) || got.sub.includes(s)) problems.push(`says "${s}"`);
    return { name: `${c.at} ${c.name}`, ok: problems.length === 0, problems, got };
  });
}

/** Logs the table; returns the number of failures. */
export function reportBannerCases(log: Pick<Console, "info" | "error"> = console): number {
  const results = runBannerCases();
  const bad = results.filter((r) => !r.ok);
  for (const r of bad) log.error(`[banner] FAIL ${r.name}: ${r.problems.join("; ")}\n  head: ${r.got.head}\n  sub:  ${r.got.sub}`);
  log.info(`[banner] ${results.length - bad.length}/${results.length} cases pass`);
  return bad.length;
}

// `node_modules/.bin/jiti lib/banner.cases.ts` → run, print every case, exit non-zero on failure.
declare const process: { argv?: string[]; exitCode?: number } | undefined;
if (typeof process !== "undefined" && process?.argv?.[1]?.endsWith("banner.cases.ts")) {
  for (const r of runBannerCases()) console.info(`${r.ok ? "ok  " : "FAIL"} ${r.name.padEnd(42)} [${r.got.reason}/${r.got.tone}] ${r.got.head} | ${r.got.sub}`);
  if (reportBannerCases()) process.exitCode = 1;
}
