import { Dashboard } from "@/components/Dashboard";
import { API_BASE, FORCE_MOCK } from "@/lib/api";
import { defaultStart, mockStateAt, mockTimelineAt } from "@/lib/mock/engine";
import { MOCK_TZ, mockHousehold } from "@/lib/mock/script";
import { todayIn } from "@/lib/time";
import type { Household, LedgerRecord, State } from "@/lib/types";
import type { InitialData } from "@/lib/useDoorLedger";

export const dynamic = "force-dynamic";

async function getJson<T>(path: string, timeoutMs = 800): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`${res.status}`);
  return (await res.json()) as T;
}

export default async function Page() {
  const date = todayIn(MOCK_TZ);
  const simStart = defaultStart(date);
  const mock: InitialData = {
    mode: "mock",
    mockReason: FORCE_MOCK ? "forced" : "unreachable",
    date,
    simStart,
    household: mockHousehold(),
    state: mockStateAt(date, simStart),
    timeline: mockTimelineAt(date, simStart),
  };

  let initial = mock;
  if (!FORCE_MOCK) {
    try {
      const [household, state, timeline] = await Promise.all([
        getJson<Household>("/api/household"),
        getJson<State>("/api/state"),
        getJson<LedgerRecord[]>("/api/timeline"),
      ]);
      initial = { mode: "live", mockReason: null, date: todayIn(household.patient.timezone), simStart, household, state, timeline };
    } catch {
      initial = mock;
    }
  }

  return <Dashboard initial={initial} />;
}
