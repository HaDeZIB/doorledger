"use client";

// Single data source for the whole UI. Two modes:
//  - live: FastAPI backend (polls /api/state, listens to /api/stream SSE)
//  - mock: fixture day + client-side demo clock (NEXT_PUBLIC_MOCK=1, or backend unreachable)

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { api, FORCE_MOCK, subscribeStream } from "./api";
import { evvCsvFromState } from "./derive";
import { DemoClock, defaultStart, mockStateAt, mockTimelineAt, resetTime, scenarioRange } from "./mock/engine";
import { mockAsk, mockSummary } from "./mock/assistant";
import { SCENARIOS, mockAmbientAt, mockHousehold, type DayVariant } from "./mock/script";
import type { AskResponse, Finding, Household, LedgerRecord, Observation, Scenario, State, SummaryResponse } from "./types";
import { dateIn } from "./time";

export type Mode = "live" | "mock";
export type MockReason = "forced" | "unreachable" | null;

export interface InitialData {
  mode: Mode;
  mockReason: MockReason;
  date: string;
  simStart: number;
  household: Household;
  state: State;
  timeline: LedgerRecord[];
}

export interface Toast {
  id: string;
  finding: Finding;
}

export function useDoorLedger(initial: InitialData) {
  const [mode, setMode] = useState<Mode>(initial.mode);
  const [mockReason, setMockReason] = useState<MockReason>(initial.mockReason);
  const [household, setHousehold] = useState<Household>(initial.household);
  const [liveState, setLiveState] = useState<State>(initial.state);
  const [liveTimeline, setLiveTimeline] = useState<LedgerRecord[]>(initial.timeline);
  const [streamConnected, setStreamConnected] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [speed, setSpeedState] = useState(60);
  const [busy, setBusy] = useState(false);

  // ----- mock clock -------------------------------------------------------------------
  const clockRef = useRef<DemoClock | null>(null);
  if (!clockRef.current) clockRef.current = new DemoClock(initial.simStart);
  const clock = clockRef.current;

  const [tick, setTick] = useState(initial.simStart);
  useEffect(() => {
    if (mode !== "mock") return;
    setTick(clock.now());
    const id = setInterval(() => setTick(clock.now()), 250);
    return () => clearInterval(id);
  }, [mode, clock]);

  const clockSnap = useSyncExternalStore(
    useCallback((cb) => clock.subscribe(cb), [clock]),
    () => clockSnapKey(clock),
    () => "idle|1",
  );

  const date = initial.date;
  // which afternoon the mock day shows; set by the last scenario played, kept after it ends
  const [variant, setVariant] = useState<DayVariant>("standard");
  const mockState = useMemo(() => (mode === "mock" ? mockStateAt(date, tick, variant) : null), [mode, date, tick, variant]);
  const mockTimeline = useMemo(() => (mode === "mock" ? mockTimelineAt(date, tick, 0, variant) : null), [mode, date, tick, variant]);

  // ----- live mode --------------------------------------------------------------------
  const refreshLive = useCallback(async () => {
    try {
      const st = await api.state();
      setLiveState(st);
      setLiveError(null);
    } catch (e) {
      setLiveError(e instanceof Error ? e.message : "Backend unreachable");
    }
  }, []);

  const goLive = useCallback(async (): Promise<boolean> => {
    try {
      const [h, st, tl] = await Promise.all([api.household(2000), api.state(), api.timeline()]);
      setHousehold(h);
      setLiveState(st);
      setLiveTimeline(tl);
      setMode("live");
      setMockReason(null);
      setLiveError(null);
      return true;
    } catch {
      return false;
    }
  }, []);

  // Client-side probe: the server render may not have reached the backend (or vice versa).
  useEffect(() => {
    if (FORCE_MOCK || initial.mode === "live") return;
    void goLive();
  }, [goLive, initial.mode]);

  useEffect(() => {
    if (mode !== "live") return;
    const poll = setInterval(refreshLive, 2500);
    let pending: ReturnType<typeof setTimeout> | null = null;
    const unsub = subscribeStream(
      (rec) => {
        // a record can be re-sent with new data (a call's outcome: placed → answered)
        setLiveTimeline((tl) => (tl.some((r) => r.id === rec.id) ? tl.map((r) => (r.id === rec.id ? rec : r)) : [...tl, rec]));
        if (!pending) {
          pending = setTimeout(() => {
            pending = null;
            void refreshLive();
          }, 150);
        }
      },
      setStreamConnected,
    );
    return () => {
      clearInterval(poll);
      if (pending) clearTimeout(pending);
      unsub();
    };
  }, [mode, refreshLive]);

  const state = mode === "mock" ? mockState! : liveState;
  // mock: the outside temperature follows the demo clock (−6 °C morning → −9 °C afternoon)
  const shownHousehold = useMemo<Household>(
    () => (mode === "mock" ? { ...household, ambient: { ...household.ambient, celsius: mockAmbientAt(state.now) } } : household),
    [mode, household, state.now],
  );
  const timeline = mode === "mock" ? mockTimeline! : liveTimeline;

  // ----- observations index (for source badges / evidence lookup) ----------------------
  const observations = useMemo(() => {
    const m = new Map<string, Observation>();
    for (const r of timeline) if (r.kind === "observation") m.set(String(r.body.id ?? r.id), r.body as unknown as Observation);
    for (const v of state.visits) for (const o of [v.check_in, v.check_out]) if (o) m.set(o.id, o);
    for (const d of state.deliveries) for (const o of [d.dropped, d.removed]) if (o) m.set(o.id, o);
    return m;
  }, [timeline, state]);

  // ----- toasts for new alerts --------------------------------------------------------
  const seen = useRef<Set<string> | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => {
    const ids = new Set(state.findings.map((f) => f.id));
    if (seen.current === null) {
      seen.current = ids;
      return;
    }
    const fresh = state.findings.filter((f) => !seen.current!.has(f.id) && f.severity !== "info");
    // a reset/rewind shrinks the set; resync without toasting
    seen.current = ids;
    if (fresh.length) setToasts((t) => [...fresh.map((f) => ({ id: f.id, finding: f })), ...t].slice(0, 3));
  }, [state.findings]);
  const dismissToast = useCallback((id: string) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  useEffect(() => {
    if (!toasts.length) return;
    const id = setTimeout(() => setToasts((t) => t.slice(0, -1)), 7000);
    return () => clearTimeout(id);
  }, [toasts]);

  // ----- demo controls ----------------------------------------------------------------
  const runScenario = useCallback(
    async (sc: Scenario) => {
      setBusy(true);
      try {
        if (mode === "mock") {
          const r = scenarioRange(date, sc);
          setVariant(SCENARIOS[sc].variant ?? "standard");
          clock.run(r.from, r.to, speed, sc);
          setTick(clock.now());
        } else {
          await api.runDemo(sc, speed);
          setLiveTimeline([]);
          // the scenario overrides the outside temperature (e.g. −9 °C for porch_cold)
          api.household(2000).then(setHousehold).catch(() => {});
          await refreshLive();
          setLiveTimeline(await api.timeline());
        }
      } catch (e) {
        setLiveError(e instanceof Error ? e.message : "Demo run failed");
      } finally {
        setBusy(false);
      }
    },
    [mode, date, clock, speed, refreshLive],
  );

  const reset = useCallback(async () => {
    setBusy(true);
    try {
      if (mode === "mock") {
        setVariant("standard");
        clock.jump(resetTime(date));
        setTick(clock.now());
      } else {
        await api.resetDemo();
        api.household(2000).then(setHousehold).catch(() => {});
        setLiveTimeline(await api.timeline());
        await refreshLive();
      }
      setToasts([]);
    } catch (e) {
      setLiveError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  }, [mode, date, clock, refreshLive]);

  const jumpTo = useCallback(
    (simMs: number) => {
      if (mode !== "mock") return;
      clock.jump(simMs);
      setTick(clock.now());
    },
    [mode, clock],
  );

  const setSpeed = useCallback(
    (s: number) => {
      setSpeedState(s);
      if (mode === "mock" && clock.snapshot().scenario) clock.setSpeed(s);
    },
    [mode, clock],
  );

  const switchToMock = useCallback(() => {
    setMode("mock");
    setMockReason("forced");
    setHousehold(mockHousehold());
    setVariant("standard");
    clock.jump(defaultStart(date));
    setTick(clock.now());
  }, [clock, date]);

  const evidenceUrl = useCallback(
    (o: Observation | null | undefined): string | null => {
      if (!o?.evidence_path) return null;
      // mock: only real frames bundled under public/ (e.g. /ring/package.jpg); never invented ones
      if (mode === "mock") return o.evidence_path.startsWith("/ring/") && o.source !== "simulated" ? o.evidence_path : null;
      return api.evidenceUrl(o.evidence_path);
    },
    [mode],
  );

  const exportEvv = useCallback(() => {
    const day = dateIn(state.now, household.patient.timezone);
    if (mode === "live") {
      window.location.href = api.evvCsvUrl(day);
      return;
    }
    const csv = evvCsvFromState(state, household.patient.name, household.patient.address, household.patient.timezone);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `evv-${day}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [mode, state, household]);

  // ----- CareAgent (Bedrock in live mode; canned answers from the fixture in mock) ------
  // Never called automatically: each call costs money. Errors propagate (ApiError.status 503 = no model).
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const ask = useCallback(
    async (question: string): Promise<AskResponse> => {
      if (mode === "mock") {
        await new Promise((r) => setTimeout(r, 700));
        return mockAsk(question, stateRef.current, household);
      }
      return api.ask(question);
    },
    [mode, household],
  );
  const summarize = useCallback(async (): Promise<SummaryResponse> => {
    if (mode === "mock") {
      await new Promise((r) => setTimeout(r, 900));
      return mockSummary(stateRef.current, household);
    }
    return api.summary();
  }, [mode, household]);

  const [scenarioName, speedNow] = clockSnap.split("|");
  return {
    mode,
    mockReason,
    household: shownHousehold,
    state,
    timeline,
    observations,
    streamConnected,
    liveError,
    busy,
    speed,
    playing: mode === "mock" && scenarioName !== "idle" ? (scenarioName as Scenario) : null,
    clockSpeed: Number(speedNow),
    toasts,
    dismissToast,
    runScenario,
    reset,
    jumpTo,
    setSpeed,
    retryLive: goLive,
    switchToMock,
    evidenceUrl,
    exportEvv,
    ask,
    summarize,
  };
}

function clockSnapKey(c: DemoClock) {
  const s = c.snapshot();
  return `${s.scenario ?? "idle"}|${s.speed}`;
}

export type DoorLedger = ReturnType<typeof useDoorLedger>;
