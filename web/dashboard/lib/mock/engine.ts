// Mock backend: derives the exact `/api/state` and `/api/timeline` shapes from the fixture
// day at any demo-clock instant, plus the client-side demo clock that plays scenarios.

import type { DeliveryState, LedgerRecord, Scenario, State, VisitState } from "../types";
import { estimate } from "../thermal";
import { evvCsvFromState } from "../derive";
import { ms, zonedISO } from "../time";
import {
  DEFAULT_START,
  MOCK_TZ,
  RESET_TIME,
  SCENARIOS,
  buildMockDay,
  mockAmbientAt,
  type MockDay,
} from "./script";

const cache = new Map<string, MockDay>();
export function mockDay(date: string): MockDay {
  let d = cache.get(date);
  if (!d) {
    d = buildMockDay(date);
    cache.set(date, d);
  }
  return d;
}

export function mockStateAt(date: string, nowMs: number): State {
  const day = mockDay(date);
  const seen = <T extends { at: string }>(x: T) => ms(x.at) <= nowMs;
  const obs = day.observations.filter(seen);
  const now = new Date(nowMs).toISOString();

  const visits: VisitState[] = day.expectations
    .filter((e) => e.kind === "caregiver_visit")
    .map((e) => {
      const check_in = obs.find((o) => o.kind === "presence_check_in" && o.visit_id === e.visit_id) ?? null;
      const check_out = obs.find((o) => o.kind === "presence_check_out" && o.visit_id === e.visit_id) ?? null;
      const minutes_on_site = check_in
        ? Math.round(((check_out ? ms(check_out.at) : nowMs) - ms(check_in.at)) / 60000)
        : null;
      return { expectation: e, check_in, check_out, minutes_on_site };
    });

  const deliveries: DeliveryState[] = day.expectations
    .filter((e) => e.kind === "medication_delivery")
    .map((e) => {
      const dropped = obs.find((o) => o.kind === "package_dropped" && o.detail.expectation_id === e.id) ?? null;
      const removed = obs.find((o) => o.kind === "package_removed" && o.detail.expectation_id === e.id) ?? null;
      let est = null;
      if (dropped && e.medication) {
        const end = removed ? ms(removed.at) : nowMs;
        // like the backend: ambient at the end of the exposure (removal, or now)
        est = estimate((end - ms(dropped.at)) / 60000, mockAmbientAt(new Date(end).toISOString()), e.medication, {
          inSun: Boolean(dropped.detail.in_sun),
        });
        // it made it inside before crossing the limit (same rule as reconcile.py)
        if (removed && est.status === "at_risk") est.status = "safe";
      }
      return { expectation: e, dropped, removed, estimate: est };
    });

  return {
    now,
    visits,
    deliveries,
    findings: day.findings.filter(seen),
    actions: day.actions.filter(seen),
  };
}

export function mockTimelineAt(date: string, nowMs: number, sinceMs = 0): LedgerRecord[] {
  return mockDay(date).records.filter((r) => ms(r.at) <= nowMs && ms(r.at) >= sinceMs);
}

export function mockEvvCsv(date: string, nowMs: number, patient: string, address: string): string {
  return evvCsvFromState(mockStateAt(date, nowMs), patient, address, MOCK_TZ);
}

// ---------------------------------------------------------------------------------------
// Demo clock: simNow = anchorSim + (wallNow - anchorWall) * speed, stopping at `untilSim`
// (then it keeps ticking at 1x, like real life).

export interface ClockSnapshot {
  anchorSim: number;
  anchorWall: number;
  speed: number;
  untilSim: number | null;
  scenario: Scenario | null;
}

export class DemoClock {
  private s: ClockSnapshot;
  private listeners = new Set<() => void>();

  constructor(startSim: number) {
    this.s = { anchorSim: startSim, anchorWall: Date.now(), speed: 1, untilSim: null, scenario: null };
  }

  now(): number {
    const { anchorSim, anchorWall, speed, untilSim } = this.s;
    const raw = anchorSim + (Date.now() - anchorWall) * speed;
    if (untilSim !== null && raw >= untilSim) {
      // scenario finished: continue in real time from the end point
      this.s = { anchorSim: untilSim, anchorWall: Date.now(), speed: 1, untilSim: null, scenario: null };
      this.emit();
      return untilSim;
    }
    return raw;
  }

  snapshot(): ClockSnapshot {
    return { ...this.s };
  }

  run(fromSim: number, toSim: number, speed: number, scenario: Scenario) {
    this.s = { anchorSim: fromSim, anchorWall: Date.now(), speed, untilSim: toSim, scenario };
    this.emit();
  }

  setSpeed(speed: number) {
    const cur = this.now();
    this.s = { ...this.s, anchorSim: cur, anchorWall: Date.now(), speed };
    this.emit();
  }

  jump(sim: number) {
    this.s = { anchorSim: sim, anchorWall: Date.now(), speed: 1, untilSim: null, scenario: null };
    this.emit();
  }

  subscribe(fn: () => void) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    this.listeners.forEach((f) => f());
  }
}

export const scenarioRange = (date: string, sc: Scenario) => ({
  from: ms(zonedISO(date, SCENARIOS[sc].from, MOCK_TZ)),
  to: ms(zonedISO(date, SCENARIOS[sc].to, MOCK_TZ)),
});
export const defaultStart = (date: string) => ms(zonedISO(date, DEFAULT_START, MOCK_TZ));
export const resetTime = (date: string) => ms(zonedISO(date, RESET_TIME, MOCK_TZ));
