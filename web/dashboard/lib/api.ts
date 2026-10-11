// Typed client for the DoorLedger FastAPI backend. See API_CONTRACT.md.

import type { AskResponse, Household, LedgerRecord, OkResponse, Scenario, State, SummaryResponse } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8787").replace(/\/$/, "");
export const FORCE_MOCK = process.env.NEXT_PUBLIC_MOCK === "1" || process.env.NEXT_PUBLIC_MOCK === "true";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const { timeoutMs = 5000, ...rest } = init;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      signal: ctrl.signal,
      cache: "no-store",
      headers: { Accept: "application/json", ...(rest.body ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, detail || `${res.status} ${res.statusText} on ${path}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  household: (timeoutMs?: number) => request<Household>("/api/household", { timeoutMs }),
  state: (at?: string) => request<State>(`/api/state${at ? `?at=${encodeURIComponent(at)}` : ""}`),
  timeline: (since?: string) =>
    request<LedgerRecord[]>(`/api/timeline${since ? `?since=${encodeURIComponent(since)}` : ""}`),
  runDemo: (scenario: Scenario, speed: number) =>
    request<OkResponse>("/api/demo/run", { method: "POST", body: JSON.stringify({ scenario, speed }) }),
  resetDemo: () => request<OkResponse>("/api/demo/reset", { method: "POST" }),
  // CareAgent calls hit Bedrock (seconds, and cost money): generous timeout, never auto-called.
  ask: (question: string) =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ question }), timeoutMs: 90000 }),
  summary: () => request<SummaryResponse>("/api/summary", { timeoutMs: 120000 }),
  // Observation.evidence_path is e.g. "evidence/captured/20261011T140702_f_x.jpg" or "evidence/package.jpg".
  // The backend route is /api/evidence/{path} and strips one leading "evidence/", so we pass the
  // path through as-is (→ /api/evidence/evidence/captured/…), which resolves under its evidence dir.
  evidenceUrl: (path: string) =>
    `${API_BASE}/api/evidence/${path.replace(/^\/+/, "").split("/").map(encodeURIComponent).join("/")}`,
  evvCsvUrl: (date: string) => `${API_BASE}/api/evv.csv?date=${encodeURIComponent(date)}`,
  streamUrl: () => `${API_BASE}/api/stream`,
};

/**
 * Subscribe to the SSE ledger stream. EventSource reconnects on its own for transient
 * drops; if the connection is closed outright we back off and reopen it ourselves.
 */
export function subscribeStream(
  onRecord: (r: LedgerRecord) => void,
  onStatus?: (connected: boolean) => void,
): () => void {
  let es: EventSource | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let backoff = 1000;

  const open = () => {
    if (closed) return;
    es = new EventSource(api.streamUrl());
    es.onopen = () => {
      backoff = 1000;
      onStatus?.(true);
    };
    es.onmessage = (ev) => {
      try {
        onRecord(JSON.parse(ev.data) as LedgerRecord);
      } catch {
        /* ignore keep-alives / malformed frames */
      }
    };
    es.onerror = () => {
      onStatus?.(false);
      if (es && es.readyState === EventSource.CLOSED) {
        es = null;
        retry = setTimeout(open, backoff);
        backoff = Math.min(backoff * 2, 15000);
      }
    };
  };
  open();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    es?.close();
  };
}
