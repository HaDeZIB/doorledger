"use client";

import type { Household, Observation, State, VisitState } from "@/lib/types";
import { firstName, visitStatus } from "@/lib/derive";
import { fmtTime, minutesBetween, ms } from "@/lib/time";
import { EvidenceFrame } from "./EvidenceFrame";
import { IconKey, IconUser } from "./icons";
import { Card, CardHeader, ProgressRing, SourceBadge, StatusChip, cx } from "./ui";

const RING_COLOR: Record<string, string> = {
  in_progress: "var(--color-brand)",
  completed: "var(--color-ok-bar)",
  short: "var(--color-warn-bar)",
  late: "var(--color-warn-bar)",
  missed: "var(--color-crit-bar)",
  awaiting: "var(--color-info)",
  scheduled: "var(--color-ink-3)",
};

export function VisitCard({
  visit,
  household,
  state,
  evidenceUrl,
}: {
  visit: VisitState | null;
  household: Household;
  state: State;
  evidenceUrl: (o: Observation | null | undefined) => string | null;
}) {
  const tz = household.patient.timezone;
  if (!visit) {
    return (
      <Card>
        <CardHeader eyebrow="Caregiver" title="No visits scheduled today" />
      </Card>
    );
  }
  const e = visit.expectation;
  const st = visitStatus(visit, state.now, state.findings);
  const planned = e.planned_minutes ?? minutesBetween(e.window_start, e.window_end);
  const onSite =
    visit.minutes_on_site ?? (visit.check_in ? Math.max(0, Math.round(minutesBetween(visit.check_in.at, state.now))) : 0);
  const who = (visit.check_in?.detail.caregiver as string | undefined) ?? e.caregiver ?? "Caregiver";
  const backup = Boolean(visit.check_in?.detail.backup);
  const late = visit.check_in ? Math.round(minutesBetween(e.window_start, visit.check_in.at)) : null;
  const waiting = !visit.check_in && ms(state.now) > ms(e.window_start) ? Math.round(minutesBetween(e.window_start, state.now)) : null;

  const headline =
    st.key === "in_progress"
      ? `${firstName(who)} is with ${firstName(household.patient.name)} now`
      : st.key === "missed"
        ? "No one has arrived"
        : st.key === "late"
          ? `Waiting for ${firstName(who)}`
          : st.key === "awaiting"
            ? `${firstName(who)} is due now`
            : st.key === "scheduled"
              ? `${firstName(who)} arrives at ${fmtTime(e.window_start, tz)}`
              : st.key === "short"
                ? "Visit was cut short"
                : "Visit completed";

  const others = state.visits.filter((v) => v.expectation.id !== e.id);
  const evidence = visit.check_out ?? visit.check_in;

  return (
    <Card aria-labelledby="visit-title">
      <CardHeader
        id="visit-title"
        eyebrow={
          <span className="inline-flex items-center gap-1.5">
            <IconUser size={15} /> {e.title}
          </span>
        }
        title={headline}
        className="xl:pt-3.5"
        titleClassName="xl:text-[1.25rem]"
        right={<StatusChip status={st.key} label={st.label} />}
      />
      <p className="px-5 pt-1 text-ink-2 sm:px-6">
        {who}
        {backup && " (backup aide)"} · {e.agency}
      </p>

      <div className="flex flex-col items-center gap-5 px-5 pt-4 sm:flex-row sm:items-center sm:px-6 xl:pt-3">
        <ProgressRing
          value={visit.check_in ? onSite / planned : 0}
          color={RING_COLOR[st.key]}
          label={`${onSite} of ${planned} planned minutes on site`}
        >
          {visit.check_in ? (
            <>
              <span className="text-4xl font-bold tabular leading-none">{onSite}</span>
              <span className="mt-1 text-sm text-ink-3">of {planned} min</span>
            </>
          ) : waiting !== null ? (
            <>
              <span className={cx("text-4xl font-bold tabular leading-none", st.key === "missed" ? "text-crit" : "text-warn")}>{waiting}</span>
              <span className="mt-1 text-sm text-ink-3">min late</span>
            </>
          ) : (
            <>
              <span className="text-2xl font-bold tabular leading-none">{planned}</span>
              <span className="mt-1 text-sm text-ink-3">min planned</span>
            </>
          )}
        </ProgressRing>

        <dl className="grid w-full flex-1 grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 text-[1.02rem]">
          <dt className="text-ink-3">Planned</dt>
          <dd className="tabular">
            {fmtTime(e.window_start, tz)} – {fmtTime(e.window_end, tz)}
          </dd>
          <dt className="text-ink-3">Checked in</dt>
          <dd>
            {visit.check_in ? (
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold tabular">{fmtTime(visit.check_in.at, tz)}</span>
                {late !== null && late > 5 && <span className="text-warn">{late} min late</span>}
                <SourceBadge source={visit.check_in.source} />
              </span>
            ) : (
              <span className="text-ink-3">Not yet</span>
            )}
          </dd>
          <dt className="text-ink-3">Checked out</dt>
          <dd>
            {visit.check_out ? (
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold tabular">{fmtTime(visit.check_out.at, tz)}</span>
                <SourceBadge source={visit.check_out.source} />
              </span>
            ) : (
              <span className="text-ink-3">{visit.check_in ? "Still there" : "—"}</span>
            )}
          </dd>
        </dl>
      </div>

      <div className="grid gap-4 px-5 pb-5 pt-4 sm:grid-cols-2 sm:px-6 xl:gap-3 xl:pb-4 xl:pt-3">
        {evidence ? (
          <div className="min-w-0">
            <p className="mb-1.5 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Proof</p>
            <EvidenceFrame
              obs={evidence}
              url={evidenceUrl(evidence)}
              alternates={visit.check_out && visit.check_in ? [{ obs: visit.check_in, url: evidenceUrl(visit.check_in) }] : []}
              tz={tz}
              wideOverlay
            />
          </div>
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-dashed border-line-strong p-6 text-center text-ink-3">
            The check-in frame will appear here.
          </div>
        )}
        <div className="min-w-0 space-y-3">
          {others.length > 0 && (
            <div>
              <p className="mb-1.5 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Other visits today</p>
              <ul className="divide-y divide-line rounded-2xl border border-line">
                {others.map((v) => {
                  const s = visitStatus(v, state.now, state.findings);
                  return (
                    <li key={v.expectation.id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate font-semibold">{v.expectation.title}</p>
                        <p className="text-sm text-ink-3 tabular">
                          {fmtTime(v.expectation.window_start, tz)}
                          {v.minutes_on_site !== null && ` · ${v.minutes_on_site} of ${v.expectation.planned_minutes} min`}
                        </p>
                      </div>
                      <StatusChip status={s.key} label={s.label} className="!px-2 !py-0.5 text-[0.8rem]" />
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          <div className="flex items-start gap-3 rounded-2xl bg-canvas p-3.5 text-ink-2">
            <IconKey size={22} className="mt-0.5 shrink-0 text-brand" />
            <p className="text-[0.95rem] xl:text-[0.88rem]">
              Aides check in by pressing the Ring doorbell, then holding a <strong className="font-semibold text-ink">rotating signed code</strong> on
              their phone up to its camera. No face recognition, no app for {firstName(household.patient.name)}.
            </p>
          </div>
          {[visit.check_in, visit.check_out].some((o) => o?.source === "simulated") && (
            <p className="text-sm text-ink-3 xl:hidden">
              Today&apos;s check-in/out is <strong className="font-semibold text-warn">simulated</strong> until our own footage of the code is filmed.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
