"use client";

import { useState } from "react";
import type { Action, Expectation, Finding, Household, LedgerKind, LedgerRecord, Observation, RingEvent } from "@/lib/types";
import { findingLabel, OBS_LABEL, actionHeadline, ringEventLabel, visionMeta, visionNote } from "@/lib/derive";
import { fmtTime, fmtTimeSec, ms } from "@/lib/time";
import { Card, CardHeader, Empty, SeverityChip, SourceBadge, cx } from "./ui";

const KIND_STYLE: Record<LedgerKind, { label: string; cls: string }> = {
  expectation: { label: "Expected", cls: "bg-[#efeee9] text-ink-2" },
  observation: { label: "Observed", cls: "bg-info-soft text-info" },
  finding: { label: "Finding", cls: "bg-warn-soft text-warn" },
  action: { label: "Action", cls: "bg-brand-soft text-brand-strong" },
  ring_event: { label: "Ring event", cls: "bg-[#efeaf8] text-[#4f3a8a]" },
};

export function LedgerView({ timeline, household }: { timeline: LedgerRecord[]; household: Household }) {
  const tz = household.patient.timezone;
  const [filter, setFilter] = useState<LedgerKind | "all">("all");
  // the Ring filter only appears once the live poller has written Ring history rows
  const kinds: LedgerKind[] = ["expectation", "observation", "finding", "action", ...(timeline.some((r) => r.kind === "ring_event") ? (["ring_event"] as const) : [])];
  const rows = [...timeline].filter((r) => filter === "all" || r.kind === filter).sort((a, b) => ms(b.at) - ms(a.at) || b.id.localeCompare(a.id));
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Audit trail</p>
        <h1 className="mt-0.5 text-3xl font-semibold tracking-tight">The ledger</h1>
        <p className="mt-1 max-w-2xl text-ink-2">
          Append-only record of everything DoorLedger expected, saw, concluded and did. Every finding links to the camera events behind it, and every
          camera event says where it came from.
        </p>
      </div>
      <Card>
        <CardHeader
          title={`${rows.length} records`}
          right={
            <div role="radiogroup" aria-label="Filter records" className="flex flex-wrap gap-1.5">
              {(["all", ...kinds] as const).map((k) => (
                <button
                  key={k}
                  role="radio"
                  aria-checked={filter === k}
                  onClick={() => setFilter(k)}
                  className={cx(
                    "rounded-full border px-3 py-1.5 text-sm font-semibold transition",
                    filter === k ? "border-ink bg-ink text-white" : "border-line-strong bg-surface text-ink-2 hover:border-ink-3",
                  )}
                >
                  {k === "all" ? "All" : KIND_STYLE[k].label}
                </button>
              ))}
            </div>
          }
        />
        <ol className="mt-4 divide-y divide-line border-t border-line">
          {rows.length === 0 && (
            <li className="p-6">
              <Empty>No records yet.</Empty>
            </li>
          )}
          {rows.map((r) => (
            <li key={r.id} className="animate-enter grid grid-cols-[4.75rem_1fr] gap-3 px-5 py-3.5 sm:grid-cols-[6.5rem_7rem_1fr] sm:px-6">
              <time className="pt-0.5 text-sm text-ink-3 tabular">{fmtTimeSec(r.at, tz)}</time>
              <span className={cx("hidden h-fit w-fit rounded-full px-2 py-0.5 text-[0.78rem] font-semibold sm:inline-block", KIND_STYLE[r.kind].cls)}>
                {KIND_STYLE[r.kind].label}
              </span>
              <RecordBody r={r} household={household} tz={tz} />
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function RecordBody({ r, household, tz }: { r: LedgerRecord; household: Household; tz: string }) {
  if (r.kind === "expectation") {
    const e = r.body as unknown as Expectation;
    return (
      <div>
        <p className="font-semibold">{e.title}</p>
        <p className="text-sm text-ink-3">
          {fmtTime(e.window_start, tz)}–{fmtTime(e.window_end, tz)} · {e.caregiver ? `${e.caregiver}, ${e.agency}` : `${e.carrier}${e.medication ? ` · ${e.medication.name}` : ""}`}
        </p>
      </div>
    );
  }
  if (r.kind === "observation") {
    const o = r.body as unknown as Observation;
    const meta = o.source !== "simulated" ? visionMeta(o) : null;
    return (
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="font-semibold">{OBS_LABEL[o.kind] ?? r.subtype}</p>
        <SourceBadge source={o.source} />
        {o.source !== "simulated" && (
          <span className="text-sm text-ink-3 tabular" title="The vision model’s own estimate of its certainty, not a calibrated probability">
            {Math.round((o.confidence ?? 0) * 100)}% (model-reported)
          </span>
        )}
        {meta && (
          <span className="text-sm text-ink-3 tabular" title={meta.title}>
            {meta.text}
          </span>
        )}
        {typeof o.detail?.description === "string" && <p className="w-full text-sm text-ink-2">{o.detail.description}</p>}
        {visionNote(o) && <p className="w-full text-sm text-ink-2">Vision: {visionNote(o)}</p>}
      </div>
    );
  }
  if (r.kind === "ring_event") {
    const e = r.body as unknown as RingEvent;
    return (
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="font-semibold">{ringEventLabel(String(e.event_type ?? r.subtype))}</p>
        <SourceBadge source="ring_history" />
        {e.action && (
          <p className="w-full text-sm text-ink-2">
            From the doorbell&apos;s Ring event history. DoorLedger asked for the event snapshot and opened a{" "}
            {e.action === "burst watch" ? "burst live view (code reader on every frame)" : "live view"}.
          </p>
        )}
      </div>
    );
  }
  if (r.kind === "finding") {
    const f = r.body as unknown as Finding;
    return (
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-semibold">{(f.kind ? findingLabel(f) : r.subtype)}</p>
          <SeverityChip severity={f.severity} />
        </div>
        <p className="text-sm text-ink-2">{f.summary}</p>
      </div>
    );
  }
  const a = r.body as unknown as Action;
  return (
    <div>
      <p className="font-semibold">{actionHeadline(a, household)}</p>
      <p className="text-sm text-ink-2">{a.message}</p>
    </div>
  );
}
