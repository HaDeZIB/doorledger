"use client";

import { useMemo, useState } from "react";
import type { DeliveryState, Finding, Household, LedgerRecord, Observation, State, VisitState } from "@/lib/types";
import { FINDING_LABEL, OBS_LABEL, firstName, visitStatus } from "@/lib/derive";
import { fmtDateLong, fmtDuration, fmtHourShort, fmtTime, minuteOfDay, ms, zonedISO, dateIn } from "@/lib/time";
import { useUnits } from "@/lib/units";
import { EvidenceFrame } from "./EvidenceFrame";
import { IconCar, IconDoor, IconPackage, IconUser } from "./icons";
import { Card, SEVERITY_STYLE, SeverityChip, SourceBadge, StatusChip, VISIT_STATUS_STYLE, cx } from "./ui";

type Sel = { type: "obs"; id: string } | { type: "finding"; id: string } | null;

interface Lane {
  key: string;
  title: string;
  subtitle: string;
  icon: React.ComponentType<{ size?: number }>;
  chip?: React.ReactNode;
  render: (ctx: RenderCtx) => React.ReactNode;
}

interface RenderCtx {
  pct: (iso: string) => number;
  pctMin: (m: number) => number;
  nowIso: string;
  select: (s: Sel) => void;
  selected: Sel;
}

export function DayTimeline({
  household,
  state,
  timeline,
  observations,
  evidenceUrl,
}: {
  household: Household;
  state: State;
  timeline: LedgerRecord[];
  observations: Map<string, Observation>;
  evidenceUrl: (o: Observation | null | undefined) => string | null;
}) {
  const tz = household.patient.timezone;
  const { fmt } = useUnits();
  const [userSel, setUserSel] = useState<Sel>(null);

  // ----- axis ------------------------------------------------------------------------
  const { startMin, endMin } = useMemo(() => {
    const exps = [...state.visits.map((v) => v.expectation), ...state.deliveries.map((d) => d.expectation)];
    if (!exps.length) return { startMin: 7 * 60, endMin: 20 * 60 };
    const s = Math.min(...exps.map((e) => minuteOfDay(e.window_start, tz)));
    const e = Math.max(...exps.map((x) => minuteOfDay(x.window_end, tz)));
    return {
      startMin: Math.max(0, Math.floor((s - 120) / 60) * 60),
      endMin: Math.min(24 * 60, Math.ceil((e + 120) / 60) * 60),
    };
  }, [state.visits, state.deliveries, tz]);
  const span = endMin - startMin;
  const day = dateIn(state.now, tz);
  const pctMin = (m: number) => Math.max(0, Math.min(100, ((m - startMin) / span) * 100));
  const pct = (iso: string) => {
    // clamp to today's axis; events on other days pin to the edges
    const d = dateIn(iso, tz);
    if (d < day) return 0;
    if (d > day) return 100;
    return pctMin(minuteOfDay(iso, tz));
  };
  const nowPct = pct(state.now);
  const hours = useMemo(() => {
    const h: number[] = [];
    for (let m = startMin; m <= endMin; m += 60) h.push(m);
    return h;
  }, [startMin, endMin]);

  // ----- lanes -----------------------------------------------------------------------
  const linked = new Set<string>();
  state.visits.forEach((v) => [v.check_in, v.check_out].forEach((o) => o && linked.add(o.id)));
  state.deliveries.forEach((d) => [d.dropped, d.removed].forEach((o) => o && linked.add(o.id)));
  const other = [...observations.values()]
    .filter((o) => !linked.has(o.id) && ms(o.at) <= ms(state.now))
    .sort((a, b) => ms(a.at) - ms(b.at));

  const findingsByExp = (id: string) => state.findings.filter((f) => f.expectation_id === id);

  const items: { at: number; lane: "v" | "d"; v?: VisitState; d?: DeliveryState }[] = [
    ...state.visits.map((v) => ({ at: ms(v.expectation.window_start), lane: "v" as const, v })),
    ...state.deliveries.map((d) => ({ at: ms(d.expectation.window_start), lane: "d" as const, d })),
  ].sort((a, b) => a.at - b.at);

  const lanes: Lane[] = items.map((it) =>
    it.lane === "v" ? visitLane(it.v!, state.now, tz, findingsByExp(it.v!.expectation.id)) : deliveryLane(it.d!, state.now, tz, findingsByExp(it.d!.expectation.id), fmt),
  );
  lanes.push({
    key: "other",
    title: "Other activity",
    subtitle: other.length ? `${other.length} event${other.length > 1 ? "s" : ""} at the door` : "Nothing unscheduled",
    icon: IconDoor,
    render: ({ pct, select, selected }) => (
      <>
        <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
        {other.map((o) => (
          <Marker
            key={o.id}
            left={pct(o.at)}
            className="bg-surface border-ink-3 text-ink-3"
            label={`${OBS_LABEL[o.kind]} at ${fmtTime(o.at, tz)}`}
            active={selected?.type === "obs" && selected.id === o.id}
            onClick={() => select({ type: "obs", id: o.id })}
            small
          />
        ))}
        {state.findings
          .filter((f) => !f.expectation_id)
          .map((f) => (
            <Flag key={f.id} left={pct(f.at)} finding={f} onClick={() => select({ type: "finding", id: f.id })} active={selected?.type === "finding" && selected.id === f.id} />
          ))}
      </>
    ),
  });

  // ----- selection -------------------------------------------------------------------
  const latestObs = [...observations.values()].filter((o) => ms(o.at) <= ms(state.now)).sort((a, b) => ms(b.at) - ms(a.at))[0];
  const selValid =
    userSel &&
    ((userSel.type === "obs" && observations.has(userSel.id)) || (userSel.type === "finding" && state.findings.some((f) => f.id === userSel.id)));
  const selected: Sel = selValid ? userSel : latestObs ? { type: "obs", id: latestObs.id } : null;
  const ctx: RenderCtx = { pct, pctMin, nowIso: state.now, select: setUserSel, selected };

  return (
    <Card aria-labelledby="timeline-title" className="overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 px-5 pt-5 sm:px-6 sm:pt-6">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">{fmtDateLong(state.now, tz)}</p>
          <h2 id="timeline-title" className="mt-0.5 text-2xl font-semibold tracking-tight sm:text-[1.7rem]">
            Care plan vs. reality
          </h2>
          <p className="mt-1 max-w-2xl text-ink-2">What was expected at Rosa&apos;s front door today, and what the Ring doorbell actually saw.</p>
        </div>
        <Legend />
      </div>

      <div className="mt-5 flex px-3 pb-3 sm:px-6">
        {/* label column (tablet+) */}
        <div className="hidden w-56 shrink-0 pr-4 md:block">
          <div className="h-8" />
          {lanes.map((l) => (
            <div key={l.key} className="flex h-[76px] items-center gap-3 border-t border-line/70">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-canvas text-ink-2">
                <l.icon size={20} />
              </span>
              <div className="min-w-0">
                <p className="truncate font-semibold leading-tight">{l.title}</p>
                <p className="truncate text-sm text-ink-3">{l.subtitle}</p>
              </div>
            </div>
          ))}
        </div>

        {/* tracks */}
        <div className="relative min-w-0 flex-1">
          {/* hour axis */}
          <div className="relative h-8">
            {hours.map((m, i) => (
              <span
                key={m}
                className={cx(
                  "absolute top-1 -translate-x-1/2 text-[0.8rem] font-medium text-ink-3 tabular",
                  (m / 60) % 3 !== 1 && "hidden sm:block",
                  (i === 0 || i === hours.length - 1) && "!hidden sm:!block",
                )}
                style={{ left: `${pctMin(m)}%` }}
              >
                {fmtHourShort(zonedISO(day, `${Math.floor(m / 60)}:00`, tz), tz)}
              </span>
            ))}
          </div>

          {/* past shading + hour grid */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 top-8">
            {hours.map((m) => (
              <div key={m} className="absolute top-0 bottom-0 w-px bg-line/60" style={{ left: `${pctMin(m)}%` }} />
            ))}
            <div className="absolute top-0 bottom-0 left-0 bg-ink/[0.025] transition-[width] duration-300" style={{ width: `${nowPct}%` }} />
          </div>

          {lanes.map((l) => (
            <div key={l.key} className="relative border-t border-line/70">
              <div className="flex items-center gap-2 pt-2 md:hidden">
                <l.icon size={16} />
                <p className="shrink-0 text-[0.95rem] font-semibold">{l.title}</p>
                <span className="min-w-0 truncate text-sm text-ink-3">· {l.subtitle}</span>
              </div>
              <div className="relative h-[64px] md:h-[76px]">{l.render(ctx)}</div>
            </div>
          ))}

          {/* now line */}
          {nowPct > 0 && nowPct < 100 && (
            <div className="pointer-events-none absolute bottom-0 top-6 z-20 transition-[left] duration-300" style={{ left: `${nowPct}%` }}>
              <div className="absolute -top-1 left-0 -translate-x-1/2 whitespace-nowrap rounded-full bg-ink px-2 py-0.5 text-[0.75rem] font-semibold text-white shadow tabular">
                Now {fmtTime(state.now, tz)}
              </div>
              <div className="absolute bottom-0 left-0 top-5 w-0.5 -translate-x-1/2 bg-ink/80" />
            </div>
          )}
        </div>
      </div>

      <SelectionDetail selected={selected} state={state} observations={observations} evidenceUrl={evidenceUrl} tz={tz} />
    </Card>
  );
}

// ---------------------------------------------------------------------------------------

function visitLane(v: VisitState, nowIso: string, tz: string, findings: Finding[]): Lane {
  const e = v.expectation;
  const st = visitStatus(v, nowIso);
  const who = (v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver ?? "Caregiver";
  return {
    key: e.id,
    title: e.title,
    subtitle: `${firstName(who)}${v.check_in?.detail.backup ? " (backup)" : ""} · ${fmtTime(e.window_start, tz)}–${fmtTime(e.window_end, tz)}`,
    icon: IconUser,
    chip: <StatusChip status={st.key} label={st.label} />,
    render: ({ pct, nowIso, select, selected }) => {
      const bandL = pct(e.window_start);
      const bandW = pct(e.window_end) - bandL;
      const missed = st.key === "missed" && !v.check_in;
      const inL = v.check_in ? pct(v.check_in.at) : null;
      const outIso = v.check_out?.at ?? (v.check_in ? nowIso : null);
      const outL = outIso ? pct(outIso) : null;
      const color = VISIT_STATUS_STYLE[st.key].bar;
      const lateMin = v.check_in ? (ms(v.check_in.at) - ms(e.window_start)) / 60000 : (ms(nowIso) - ms(e.window_start)) / 60000;
      const showLate = lateMin > 10 && ms(nowIso) > ms(e.window_start);
      return (
        <>
          <Band
            left={bandL}
            width={bandW}
            tone={missed ? "crit" : "plan"}
            label={missed ? "No one came" : `Planned ${e.planned_minutes ?? ""} min`}
            showLabel={missed || (!v.check_in && !showLate)}
          />
          {showLate && (inL !== null || st.key === "late" || st.key === "missed") && (
            <div
              className="absolute top-1/2 h-0 -translate-y-1/2 border-t-2 border-dashed border-warn-bar"
              style={{ left: `${bandL}%`, width: `${(inL ?? pct(nowIso)) - bandL}%` }}
            >
              {((inL ?? pct(nowIso)) - bandL > 3) && (
                <span className="absolute -top-6 left-1/2 hidden -translate-x-1/2 whitespace-nowrap text-[0.75rem] font-semibold text-warn sm:block">
                  {Math.round(lateMin)} min late
                </span>
              )}
            </div>
          )}
          {inL !== null && outL !== null && (
            <div className={cx("absolute top-1/2 h-3.5 -translate-y-1/2 rounded-full transition-[width] duration-300", color)} style={{ left: `${inL}%`, width: `${Math.max(outL - inL, 0.4)}%` }}>
              {v.minutes_on_site !== null && outL - inL > 4 && (
                <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 whitespace-nowrap text-[0.75rem] font-semibold text-ink-2 tabular">
                  {v.minutes_on_site} of {e.planned_minutes} min
                </span>
              )}
            </div>
          )}
          {v.check_in && (
            <Marker left={inL!} className={cx("border-surface text-white", color)} label={`Checked in ${fmtTime(v.check_in.at, tz)}`} active={selected?.type === "obs" && selected.id === v.check_in.id} onClick={() => select({ type: "obs", id: v.check_in!.id })} />
          )}
          {v.check_out && (
            <Marker left={outL!} className={cx("border-surface text-white", color)} label={`Checked out ${fmtTime(v.check_out.at, tz)}`} active={selected?.type === "obs" && selected.id === v.check_out.id} onClick={() => select({ type: "obs", id: v.check_out!.id })} />
          )}
          {v.check_in && !v.check_out && <Pulse left={outL!} className="text-brand" />}
          {findings
            .filter((f) => f.severity !== "info")
            .map((f) => (
              <Flag key={f.id} left={pct(f.at)} finding={f} onClick={() => select({ type: "finding", id: f.id })} active={selected?.type === "finding" && selected.id === f.id} />
            ))}
        </>
      );
    },
  };
}

function deliveryLane(d: DeliveryState, nowIso: string, tz: string, findings: Finding[], fmt: (c: number) => string): Lane {
  const e = d.expectation;
  const est = d.estimate;
  return {
    key: e.id,
    title: e.title,
    subtitle: `${e.carrier?.replace(" courier", "") ?? "Pharmacy"} · ${fmtTime(e.window_start, tz)}–${fmtTime(e.window_end, tz)}`,
    icon: IconPackage,
    render: ({ pct, nowIso: n, select, selected }) => {
      const bandL = pct(e.window_start);
      const bandW = pct(e.window_end) - bandL;
      const dL = d.dropped ? pct(d.dropped.at) : null;
      const endIso = d.removed?.at ?? (d.dropped ? n : null);
      const rL = endIso ? pct(endIso) : null;
      const statusColor =
        est?.status === "compromised" ? "var(--color-crit-bar)" : est?.status === "at_risk" ? "var(--color-warn-bar)" : "var(--color-ok-bar)";
      const deadlineIso =
        d.dropped && !d.removed && est?.minutes_until_excursion_max != null && est.minutes_until_excursion_max > 0
          ? new Date(ms(n) + est.minutes_until_excursion_max * 60000).toISOString()
          : null;
      return (
        <>
          <Band left={bandL} width={bandW} tone="plan" label="Delivery window" showLabel={!d.dropped} />
          {dL !== null && rL !== null && (
            <div
              className="absolute top-1/2 h-3.5 -translate-y-1/2 rounded-full transition-[width] duration-300"
              style={{ left: `${dL}%`, width: `${Math.max(rL - dL, 0.4)}%`, background: `linear-gradient(90deg, var(--color-cold), ${statusColor})` }}
            >
              {est && (
                <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 whitespace-nowrap text-[0.75rem] font-semibold text-ink-2 tabular">
                  {fmtDuration(est.minutes_on_porch)} outside · {fmt(est.estimated_internal_c)}
                </span>
              )}
            </div>
          )}
          {deadlineIso && pct(deadlineIso) < 100 && (
            <div className="absolute bottom-2 top-2 w-0 border-l-2 border-dashed border-crit-bar" style={{ left: `${pct(deadlineIso)}%` }} title={`Estimated unsafe at ${fmtTime(deadlineIso, tz)}`}>
              <span className="absolute -top-0.5 left-1 whitespace-nowrap text-[0.72rem] font-semibold text-crit">unsafe ~{fmtTime(deadlineIso, tz)}</span>
            </div>
          )}
          {d.dropped && (
            <Marker left={dL!} className="border-surface bg-cold text-white" label={`Left at door ${fmtTime(d.dropped.at, tz)}`} active={selected?.type === "obs" && selected.id === d.dropped.id} onClick={() => select({ type: "obs", id: d.dropped!.id })} />
          )}
          {d.removed && (
            <Marker left={rL!} className="border-surface bg-ok-bar text-white" label={`Taken inside ${fmtTime(d.removed.at, tz)}`} active={selected?.type === "obs" && selected.id === d.removed.id} onClick={() => select({ type: "obs", id: d.removed!.id })} />
          )}
          {d.dropped && !d.removed && <Pulse left={rL!} className={est?.status === "safe" ? "text-ok-bar" : est?.status === "at_risk" ? "text-warn-bar" : "text-crit-bar"} />}
          {findings
            .filter((f) => f.severity !== "info")
            .map((f) => (
              <Flag key={f.id} left={pct(f.at)} finding={f} onClick={() => select({ type: "finding", id: f.id })} active={selected?.type === "finding" && selected.id === f.id} />
            ))}
          {!d.dropped && ms(nowIso) > ms(e.window_end) && (
            <span className="absolute top-1/2 -translate-y-1/2 text-sm font-semibold text-crit" style={{ left: `${pct(e.window_end) + 1}%` }}>
              not delivered
            </span>
          )}
        </>
      );
    },
  };
}

// ---------------------------------------------------------------------------------------

function Band({ left, width, tone, label, showLabel }: { left: number; width: number; tone: "plan" | "crit"; label: string; showLabel: boolean }) {
  return (
    <div
      className={cx(
        "absolute bottom-3 top-3 rounded-xl border-2 border-dashed",
        tone === "plan" ? "hatch border-line-strong bg-canvas/60" : "border-crit-bar/60 bg-crit-soft",
      )}
      style={{ left: `${left}%`, width: `${width}%` }}
    >
      {showLabel && width > 7 && (
        <span className={cx("absolute left-2 top-0.5 hidden whitespace-nowrap text-[0.7rem] font-semibold uppercase tracking-wide lg:block", tone === "crit" ? "text-crit" : "text-ink-3")}>
          {label}
        </span>
      )}
    </div>
  );
}

function Marker({
  left,
  className,
  label,
  onClick,
  active,
  small,
}: {
  left: number;
  className: string;
  label: string;
  onClick: () => void;
  active?: boolean;
  small?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={cx(
        "absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] shadow-sm transition-transform duration-200 hover:scale-125 animate-enter",
        small ? "h-3.5 w-3.5 border-2" : "h-4 w-4 sm:h-5 sm:w-5",
        active && "scale-125 ring-4 ring-brand/30",
        className,
      )}
      style={{ left: `${left}%` }}
    />
  );
}

function Pulse({ left, className }: { left: number; className: string }) {
  return (
    <span className={cx("pointer-events-none absolute top-1/2 z-10 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current animate-pulse-ring", className)} style={{ left: `${left}%` }} />
  );
}

function Flag({ left, finding, onClick, active }: { left: number; finding: Finding; onClick: () => void; active?: boolean }) {
  const s = SEVERITY_STYLE[finding.severity];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${FINDING_LABEL[finding.kind]}: ${finding.summary}`}
      title={`${FINDING_LABEL[finding.kind]}: ${finding.summary}`}
      className={cx("absolute top-0 z-10 hidden -translate-x-1/2 animate-enter transition-transform hover:scale-125 sm:block", active && "scale-125")}
      style={{ left: `${left}%` }}
    >
      <span className={cx("block h-3 w-3 rotate-45 rounded-[3px] ring-2 ring-surface", s.bar)} />
    </button>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-2" aria-label="Legend">
      <li className="flex items-center gap-2">
        <span className="hatch inline-block h-4 w-7 rounded-md border-2 border-dashed border-line-strong" /> Expected
      </li>
      <li className="flex items-center gap-2">
        <span className="inline-block h-2.5 w-7 rounded-full bg-ok-bar" /> Observed
      </li>
      <li className="flex items-center gap-2">
        <span className="inline-block h-3 w-3 rounded-full border-2 border-surface bg-cold shadow" /> Camera event
      </li>
      <li className="flex items-center gap-2">
        <span className="inline-block h-2.5 w-2.5 rotate-45 rounded-[2px] bg-warn-bar" /> Alert
      </li>
    </ul>
  );
}

function SelectionDetail({
  selected,
  state,
  observations,
  evidenceUrl,
  tz,
}: {
  selected: Sel;
  state: State;
  observations: Map<string, Observation>;
  evidenceUrl: (o: Observation | null | undefined) => string | null;
  tz: string;
}) {
  if (!selected) {
    return (
      <div className="border-t border-line bg-canvas/50 px-5 py-4 text-ink-3 sm:px-6">Nothing seen at the door yet today. Tap any marker for details.</div>
    );
  }
  if (selected.type === "finding") {
    const f = state.findings.find((x) => x.id === selected.id)!;
    const obs = f.observation_ids.map((id) => observations.get(id)).filter(Boolean) as Observation[];
    return (
      <div className="flex flex-col gap-3 border-t border-line bg-canvas/50 px-5 py-4 sm:flex-row sm:items-center sm:px-6" aria-live="polite">
        <div className="flex items-center gap-2">
          <SeverityChip severity={f.severity} />
          <span className="font-semibold">{FINDING_LABEL[f.kind]}</span>
          <span className="text-ink-3 tabular">{fmtTime(f.at, tz)}</span>
        </div>
        <p className="flex-1 text-ink-2">{f.summary}</p>
        <div className="flex flex-wrap gap-1.5">
          {obs.map((o) => (
            <SourceBadge key={o.id} source={o.source} />
          ))}
        </div>
      </div>
    );
  }
  const o = observations.get(selected.id);
  if (!o) return null;
  const desc = (o.detail.description as string | undefined) ?? (o.detail.caregiver ? `${o.detail.caregiver}${o.detail.backup ? " (backup aide)" : ""} · rotating code verified` : "");
  return (
    <div className="flex flex-col gap-4 border-t border-line bg-canvas/50 px-5 py-4 sm:flex-row sm:items-center sm:px-6" aria-live="polite">
      <EvidenceFrame obs={o} url={evidenceUrl(o)} tz={tz} compact className="w-full shrink-0 sm:w-56" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Selected camera event</p>
        <p className="mt-0.5 text-lg font-semibold">
          {OBS_LABEL[o.kind]} <span className="font-normal text-ink-3 tabular">at {fmtTime(o.at, tz)}</span>
        </p>
        {desc && <p className="text-ink-2">{desc}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-2">
          <SourceBadge source={o.source} />
          <span className="tabular">{Math.round(o.confidence * 100)}% confidence</span>
          {o.kind === "vehicle_arrived" && <IconCar size={16} />}
        </div>
      </div>
    </div>
  );
}
