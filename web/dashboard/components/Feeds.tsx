"use client";

import type { Action, Household, Observation, State } from "@/lib/types";
import { findingLabel, actionDeliveryLabel, actionHeadline, latestFindings } from "@/lib/derive";
import { fmtTime, ms } from "@/lib/time";
import { IconBell, IconBuilding, IconLedger, IconMail, IconMessage, IconPhone, IconUser } from "./icons";
import { Card, CardHeader, Empty, SEVERITY_STYLE, SourceBadge, cx } from "./ui";

export function FindingsFeed({ state, observations, tz }: { state: State; observations: Map<string, Observation>; tz: string }) {
  // one row per (visit/delivery, kind): e.g. "late, not here yet" is replaced by "arrived 22 min late"
  const items = latestFindings(state.findings).sort((a, b) => ms(b.at) - ms(a.at));
  return (
    <Card aria-labelledby="findings-title">
      <CardHeader id="findings-title" eyebrow="What DoorLedger noticed" title="Findings" right={<Count n={items.length} />} />
      <ol className="max-h-[40rem] space-y-3 overflow-y-auto px-5 pb-6 pt-4 sm:px-6" aria-live="polite">
        {items.length === 0 && <Empty>Nothing unusual yet. Findings appear only when reality differs from the plan.</Empty>}
        {items.map((f) => {
          const s = SEVERITY_STYLE[f.severity];
          const Icon = s.icon;
          const obs = f.observation_ids.map((id) => observations.get(id)).filter(Boolean) as Observation[];
          return (
            <li key={f.id} className="animate-enter relative overflow-hidden rounded-2xl border border-line bg-surface pl-4">
              <span className={cx("absolute inset-y-0 left-0 w-1.5", s.bar)} aria-hidden />
              <div className="flex gap-3 px-3 py-3">
                <span className={cx("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full", s.chip)}>
                  <Icon size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className="font-semibold">
                      {findingLabel(f)}
                      <span className="sr-only"> ({s.label})</span>
                    </p>
                    <time className="text-sm text-ink-3 tabular">{fmtTime(f.at, tz)}</time>
                  </div>
                  <p className="mt-0.5 text-ink-2">{f.summary}</p>
                  {obs.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-sm text-ink-3">
                      <span>Based on</span>
                      {obs.map((o) => (
                        <SourceBadge key={o.id} source={o.source} />
                      ))}
                    </div>
                  )}
                  {obs.length === 0 && (f.kind === "late_arrival" || f.kind === "missed_visit") && (
                    <p className="mt-2 text-sm text-ink-3">Based on: no check-in seen by the Ring doorbell</p>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

const CHANNEL_ICON: Record<string, React.ComponentType<{ size?: number }>> = {
  sms: IconMessage,
  voice: IconPhone,
  push: IconBell,
  app: IconBell,
  agency_portal: IconBuilding,
  email: IconMail,
};

export function ActionsFeed({ state, household, tz }: { state: State; household: Household; tz: string }) {
  const items = [...state.actions].sort((a, b) => ms(b.at) - ms(a.at));
  return (
    <Card aria-labelledby="actions-title">
      <CardHeader id="actions-title" eyebrow="What DoorLedger did" title="Actions taken" right={<Count n={items.length} />} />
      <ol className="max-h-[40rem] space-y-3 overflow-y-auto px-5 pb-6 pt-4 sm:px-6" aria-live="polite">
        {items.length === 0 && <Empty>No one needed to be contacted.</Empty>}
        {items.map((a) => (
          <ActionRow key={a.id} a={a} household={household} tz={tz} />
        ))}
      </ol>
    </Card>
  );
}

function ActionRow({ a, household, tz }: { a: Action; household: Household; tz: string }) {
  const channel = String(a.data.channel ?? "");
  const Icon = a.kind === "export_evv" ? IconLedger : (CHANNEL_ICON[channel] ?? IconUser);
  const dl = actionDeliveryLabel(a);
  return (
    <li className="animate-enter flex gap-3 rounded-2xl border border-line px-3 py-3">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
        <Icon size={17} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="font-semibold">{actionHeadline(a, household)}</p>
          <time className="text-sm text-ink-3 tabular">{fmtTime(a.at, tz)}</time>
        </div>
        <p className="mt-1 rounded-xl bg-canvas px-3 py-2 text-[0.95rem] text-ink-2">“{a.message}”</p>
        <p
          className={cx(
            "mt-1.5 inline-flex items-center gap-1.5 text-sm font-semibold",
            dl.tone === "ok" ? "text-ok" : dl.tone === "warn" ? "text-warn" : "text-ink-3",
          )}
        >
          <span className={cx("h-2 w-2 rounded-full", dl.tone === "ok" ? "bg-ok-bar" : dl.tone === "warn" ? "bg-warn-bar" : "bg-ink-3")} />
          {dl.text}
        </p>
      </div>
    </li>
  );
}

function Count({ n }: { n: number }) {
  return <span className="rounded-full bg-canvas px-2.5 py-1 text-sm font-semibold text-ink-2 tabular">{n}</span>;
}
