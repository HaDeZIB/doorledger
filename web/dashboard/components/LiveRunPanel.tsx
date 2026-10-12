"use client";

// Live end-to-end run (scripts/live_demo.py): each step from the Ring event to the call, with
// real timestamps and measured latencies, read from GET /api/live/trace. Renders nothing in
// mock mode or when no live run has happened on this backend.

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { Mode } from "@/lib/useDoorLedger";
import { Card, cx } from "./ui";

interface TraceStep {
  step: string;
  label: string;
  at: string;
  t_ms: number | null;
  detail: Record<string, unknown>;
}

interface LiveTrace {
  run_id: string;
  active: boolean;
  source: "live" | "rehearsal";
  dry_run: boolean;
  trigger: string;
  device: { id?: string | null; name?: string | null };
  caps: { max_calls: number; max_sms: number; full_ladder: boolean };
  ambient: { celsius: number | null; source: string };
  steps: TraceStep[];
  latency: Record<string, number | string | null>;
}

const PIPELINE: { step: string; title: string; pick?: (s: TraceStep) => boolean }[] = [
  { step: "ring_event", title: "Ring event" },
  { step: "frame", title: "Frame" },
  { step: "vision", title: "Nova 2 Lite", pick: (s) => s.detail.package_visible === true },
  { step: "porch", title: "Porch k-of-n", pick: (s) => s.detail.observation === "package_dropped" },
  { step: "finding", title: "Finding" },
  { step: "call", title: "Call" },
  { step: "sms", title: "SMS" },
  { step: "call_outcome", title: "Answered?" },
];

function clock(iso: string, tz: string) {
  // Rosa's local time, like every other time on the dashboard, with seconds.
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function secs(ms: number | null | undefined) {
  return ms == null ? "" : `${ms >= 0 ? "+" : "−"}${(Math.abs(ms) / 1000).toFixed(1)} s`;
}

function stepNote(s: TraceStep): string {
  const d = s.detail;
  switch (s.step) {
    case "ring_event":
      return `${d.event_type ?? "event"} · history row`;
    case "frame":
      return `${d.source === "ring_snapshot" ? `${d.count ?? 1} snapshot(s)` : "WHEP live view"} · ${d.ms ?? "?"} ms`;
    case "vision":
      return d.cached ? "recorded label" : `${d.ms ?? "?"} ms · ${d.package_visible ? "package on porch" : "no package"}`;
    case "porch":
      return String(d.observation ?? "").replace("_", " ");
    case "finding":
      return String(d.finding ?? "").replace("_", " ");
    case "call":
      return d.status === "placed" ? `placed · Connect ${d.connect_ms ?? "?"} ms` : String(d.status ?? "");
    case "sms":
      return d.delivered ? `sent · SNS ${d.api_ms ?? "?"} ms` : "not sent (dry run)";
    case "call_outcome":
      return String(d.status ?? "").replace("_", " ");
    default:
      return "";
  }
}

export function LiveRunPanel({ mode, tz }: { mode: Mode; tz: string }) {
  const [trace, setTrace] = useState<LiveTrace | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      let next = 3000;
      try {
        const res = await fetch(`${API_BASE}/api/live/trace`, { cache: "no-store" });
        if (res.ok) {
          const t = (await res.json()) as LiveTrace;
          if (!stop) setTrace(t);
          if (t.active) next = 1000;
        } else if (!stop) setTrace(null);
      } catch {
        /* backend away: keep the last trace */
      }
      if (!stop) timer = setTimeout(tick, next);
    };
    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [mode]);

  if (mode !== "live" || !trace) return null;

  const first = (step: string, pick?: (s: TraceStep) => boolean) =>
    trace.steps.find((s) => s.step === step && (!pick || pick(s))) ?? trace.steps.find((s) => s.step === step);
  const toCall = trace.latency.ring_event_to_call_ms as number | null;
  const toDecision = trace.latency.ring_event_to_decision_ms as number | null;
  const problems = trace.steps.filter((s) => ["error", "suppressed", "skipped"].includes(s.step)).slice(-3);
  const rehearsal = trace.source === "rehearsal";
  const vision = first("vision");
  const privacy = vision
    ? ` Before Bedrock: ${vision.detail.privacy_zones_masked ?? 0} Ring privacy zone(s) blacked out, ${vision.detail.faces_pixelated ?? 0} face(s) pixelated.`
    : "";

  return (
    <Card className="px-5 py-4 sm:px-6" aria-label="Live Ring run">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold uppercase tracking-[0.08em]">
          <span
            className={cx(
              "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5",
              rehearsal ? "bg-warn-soft text-warn" : "bg-brand-soft text-brand-strong",
            )}
          >
            {trace.active && !rehearsal && <span className="h-2 w-2 animate-pulse rounded-full bg-current" aria-hidden />}
            {rehearsal ? "Rehearsal · recorded Playground data" : "Live · Ring Developer Playground"}
          </span>
          <span className="text-ink-3">
            {trace.device.name ?? "Ring device"} {trace.device.id ?? ""} · {trace.trigger} trigger
            {trace.dry_run && !rehearsal ? " · dry run (nothing sent)" : ""}
          </span>
        </p>
        <p className="text-lg font-semibold tabular text-ink">
          {toCall != null
            ? `Ring event → call placed in ${(toCall / 1000).toFixed(1)} s`
            : toDecision != null
              ? `Ring event → decision in ${(toDecision / 1000).toFixed(1)} s`
              : trace.active
                ? "Waiting for a Ring event…"
                : "Run ended"}
        </p>
      </div>
      <ol className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {PIPELINE.map(({ step, title, pick }) => {
          const s = first(step, pick);
          return (
            <li
              key={step}
              className={cx(
                "rounded-2xl border px-3 py-2",
                s ? "border-line bg-canvas" : "border-dashed border-line text-ink-3",
              )}
            >
              <p className="text-[0.78rem] font-semibold uppercase tracking-wide text-ink-3">{title}</p>
              {s ? (
                <>
                  <p className="tabular text-sm font-semibold text-ink">
                    {clock(s.at, tz)} <span className="font-normal text-ink-2">{secs(s.t_ms)}</span>
                  </p>
                  <p className="truncate text-[0.8rem] text-ink-2" title={stepNote(s)}>
                    {stepNote(s)}
                  </p>
                </>
              ) : (
                <p className="text-sm">—</p>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-[0.8rem] text-ink-3">
        Times are Rosa&rsquo;s local time; +s is measured from Ring&rsquo;s own timestamp of the event. Safety cap: {trace.caps.max_calls} call,{" "}
        {trace.caps.max_sms} SMS{trace.caps.full_ladder ? "" : ", no re-call, no Luis/Ana"}.
        {privacy}
        {trace.ambient.celsius != null && ` Outside temperature set to ${trace.ambient.celsius} °C for the story.`}
        {problems.map((p) => ` ${p.label}: ${String(p.detail.what ?? p.detail.reason ?? "")}.`)}
      </p>
    </Card>
  );
}
