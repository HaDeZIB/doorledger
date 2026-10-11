"use client";

import type { DeliveryState, Household, Observation, State } from "@/lib/types";
import { actionDeliveryLabel, actionHeadline, actionsForFindings, escalationChain, findingsFor, firstName, personFor } from "@/lib/derive";
import { fmtClock, fmtDuration, fmtTime, ms } from "@/lib/time";
import { useUnits } from "@/lib/units";
import { EvidenceFrame } from "./EvidenceFrame";
import { IconCheck, IconClock, IconPackage, IconThermo } from "./icons";
import { Card, CardHeader, Pill, cx } from "./ui";

const CHANNEL_VERB: Record<string, string> = { sms: "Texted", voice: "Called", app: "App alert", push: "App alert", email: "Emailed" };

const STATUS = {
  safe: { label: "Safe for now", chip: "bg-ok-soft text-ok", text: "text-ok", ring: "border-ok-bar" },
  at_risk: { label: "At risk", chip: "bg-warn-soft text-warn", text: "text-warn", ring: "border-warn-bar" },
  compromised: { label: "Likely compromised", chip: "bg-crit-soft text-crit", text: "text-crit", ring: "border-crit-bar" },
} as const;

export function MedicationCard({
  delivery,
  household,
  state,
  evidenceUrl,
}: {
  delivery: DeliveryState | null;
  household: Household;
  state: State;
  evidenceUrl: (o: Observation | null | undefined) => string | null;
}) {
  const tz = household.patient.timezone;
  const { fmt, alt } = useUnits();
  if (!delivery) {
    return (
      <Card>
        <CardHeader eyebrow="Medication" title="No deliveries expected today" />
        <p className="px-6 pb-6 pt-2 text-ink-2">DoorLedger will watch the porch whenever a pharmacy delivery is scheduled.</p>
      </Card>
    );
  }
  const e = delivery.expectation;
  const med = e.medication;
  const est = delivery.estimate;
  const onPorch = Boolean(delivery.dropped && !delivery.removed);
  const inside = Boolean(delivery.removed);
  const st = est ? STATUS[est.status] : null;
  const pill =
    inside && est && est.status !== "compromised"
      ? { label: "Inside · OK", chip: "bg-ok-soft text-ok" }
      : inside && est
        ? { label: "Inside · too warm", chip: "bg-crit-soft text-crit" }
        : st;

  const title = onPorch ? "Medication on the porch" : inside ? "Medication brought inside" : "Medication delivery expected";
  const findings = findingsFor(state, e.id);
  const actions = actionsForFindings(state, findings);

  return (
    <Card aria-labelledby="med-title" className={cx("relative overflow-hidden", onPorch && est?.status !== "safe" && "ring-2 ring-offset-0", onPorch && est?.status === "at_risk" && "ring-warn-bar/50", onPorch && est?.status === "compromised" && "ring-crit-bar/50")}>
      <CardHeader
        id="med-title"
        eyebrow={
          <span className="inline-flex items-center gap-1.5">
            <IconPackage size={15} /> {e.title}
          </span>
        }
        title={title}
        right={pill && <Pill className={pill.chip}>{pill.label}</Pill>}
      />
      <p className="px-5 pt-1 text-ink-2 sm:px-6">
        {med?.name ?? "Medication"} from {e.carrier?.replace(" courier", "") ?? "pharmacy"}
        {e.tracking && <span className="text-ink-3"> · #{e.tracking}</span>}
      </p>

      {!delivery.dropped ? (
        <div className="px-5 pb-6 pt-4 sm:px-6">
          <div className="flex items-center gap-4 rounded-2xl bg-canvas p-4">
            <IconClock size={28} />
            <div>
              <p className="text-lg font-semibold">
                Expected {fmtTime(e.window_start, tz)} – {fmtTime(e.window_end, tz)}
              </p>
              <p className="text-ink-2">
                {ms(state.now) > ms(e.window_end)
                  ? "Not delivered yet. The window has passed."
                  : `We'll watch the porch and start a heat clock the moment it's left${med ? ` (limit ${fmt(med.excursion_max_c)})` : ""}.`}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 px-5 pt-5 sm:gap-4 sm:px-6">
            {/* exposure clock */}
            <div className="min-w-0 rounded-2xl bg-canvas p-3.5 sm:p-4">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-3">
                <IconClock size={16} /> {inside ? "Time it spent outside" : "Outside for"}
              </p>
              <p className={cx("mt-1 font-mono text-[2.1rem] font-bold tracking-tight tabular sm:text-[3.4rem]", onPorch ? st?.text : "text-ink")} aria-live="off">
                {est ? fmtClock(est.minutes_on_porch) : "--:--"}
              </p>
              <p className="mt-1 text-ink-2">
                Left at {fmtTime(delivery.dropped.at, tz)}
                {delivery.removed && <> · taken in {fmtTime(delivery.removed.at, tz)}</>}
              </p>
            </div>
            {/* box temperature */}
            <div className="min-w-0 rounded-2xl bg-canvas p-3.5 sm:p-4">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-3">
                <IconThermo size={16} /> Estimated inside the box
              </p>
              <p className={cx("mt-1 text-[2.1rem] font-bold tracking-tight tabular sm:text-[3.4rem]", st?.text)}>
                {est ? fmt(est.estimated_internal_c, 1) : "—"}
              </p>
              <p className="mt-1 text-ink-2">
                {est && <>{alt(est.estimated_internal_c, 1)} · outside {fmt(est.ambient_c)}</>}
              </p>
            </div>
          </div>

          {est && med && <ThermoBar internal={est.estimated_internal_c} med={med} fmt={fmt} />}

          <div className="px-5 sm:px-6">
            <Countdown delivery={delivery} />
          </div>

          <div className="grid gap-5 px-5 pb-6 pt-5 sm:grid-cols-[1fr_1.15fr] sm:px-6">
            <div>
              <p className="mb-2 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Proof</p>
              <EvidenceFrame
                obs={delivery.removed ?? delivery.dropped}
                url={evidenceUrl(delivery.removed ?? delivery.dropped)}
                alternates={delivery.removed ? [{ obs: delivery.dropped, url: evidenceUrl(delivery.dropped) }] : []}
                tz={tz}
              />
            </div>
            <Escalation household={household} actions={actions} tz={tz} done={inside} />
          </div>
        </>
      )}
    </Card>
  );
}

function ThermoBar({ internal, med, fmt }: { internal: number; med: NonNullable<DeliveryState["expectation"]["medication"]>; fmt: (c: number) => string }) {
  const lo = 0;
  const hi = Math.max(med.excursion_max_c + 8, 38);
  const p = (c: number) => `${Math.max(0, Math.min(100, ((c - lo) / (hi - lo)) * 100))}%`;
  return (
    <div className="px-5 pt-5 sm:px-6" aria-label={`Estimated ${fmt(internal)}, storage ${fmt(med.store_min_c)}–${fmt(med.store_max_c)}, unsafe above ${fmt(med.excursion_max_c)}`} role="img">
      <div className="relative h-3 overflow-hidden rounded-full">
        <div className="absolute inset-y-0 bg-[#cfe2f5]" style={{ left: p(lo), width: p(med.store_max_c) }} />
        <div className="absolute inset-y-0 bg-[#f5e7c4]" style={{ left: p(med.store_max_c), right: `calc(100% - ${p(med.excursion_max_c)})` }} />
        <div className="absolute inset-y-0 right-0 bg-[#f6cfd1]" style={{ left: p(med.excursion_max_c) }} />
      </div>
      <div className="relative h-0">
        <div className="absolute -top-[18px] h-6 w-1.5 -translate-x-1/2 rounded-full bg-ink shadow transition-[left] duration-500" style={{ left: p(internal) }} />
      </div>
      <div className="relative mt-1.5 h-5 text-[0.78rem] font-medium text-ink-3">
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: p((med.store_min_c + med.store_max_c) / 2) }}>
          fridge
        </span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap text-crit" style={{ left: p(med.excursion_max_c) }}>
          unsafe {fmt(med.excursion_max_c)}
        </span>
      </div>
    </div>
  );
}

function Countdown({ delivery }: { delivery: DeliveryState }) {
  const est = delivery.estimate;
  if (!est) return null;
  if (delivery.removed) {
    const ok = est.status !== "compromised";
    return (
      <div className={cx("mt-4 flex items-center gap-3 rounded-2xl px-4 py-3", ok ? "bg-ok-soft text-ok" : "bg-crit-soft text-crit")}>
        <IconCheck size={22} />
        <p className="text-lg font-semibold">
          {ok ? "Inside, never reached the unsafe limit." : "Brought inside, but it likely got too warm. Call the pharmacy before using it."}
        </p>
      </div>
    );
  }
  if (est.status === "compromised") {
    return (
      <div className="mt-4 rounded-2xl bg-crit-soft px-4 py-3 text-crit">
        <p className="text-lg font-semibold">Past the safe limit. Don&apos;t use it until the pharmacy says it&apos;s OK.</p>
      </div>
    );
  }
  const left = est.minutes_until_excursion_max;
  return (
    <div className={cx("mt-4 flex flex-wrap items-baseline justify-between gap-2 rounded-2xl px-4 py-3", est.status === "at_risk" ? "bg-warn-soft text-warn animate-flash" : "bg-ok-soft text-ok")}>
      <p className="text-lg font-semibold">{left === null ? "Won't overheat at today's temperature" : est.status === "at_risk" ? "Bring it inside now" : "Needs to come inside soon"}</p>
      {left !== null && (
        <p className="text-lg tabular">
          unsafe in <span className="text-2xl font-bold">{fmtDuration(left)}</span>
        </p>
      )}
    </div>
  );
}

function Escalation({ household, actions, tz, done }: { household: Household; actions: State["actions"]; tz: string; done: boolean }) {
  const chain = escalationChain(household);
  return (
    <div>
      <p className="mb-2 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Who we&apos;ve contacted</p>
      <ol className="relative space-y-3">
        {chain.map((p, i) => {
          const mine = actions.filter((a) => personFor(household, a.target)?.name === p.name);
          // reached = they answered/replied; contacted = message delivered; unanswered = only failed attempts
          const reached = mine.some((a) => Boolean(a.data.reply) || a.data.status === "answered");
          const contacted = mine.some((a) => a.delivered);
          const tried = mine.length > 0;
          return (
            <li key={p.name} className="relative flex gap-3">
              {i < chain.length - 1 && <span className="absolute left-[15px] top-8 h-[calc(100%-12px)] w-0.5 bg-line" aria-hidden />}
              <span
                className={cx(
                  "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold",
                  reached
                    ? "border-ok-bar bg-ok-soft text-ok"
                    : contacted
                      ? "border-brand bg-brand-soft text-brand-strong"
                      : tried
                        ? "border-warn-bar bg-warn-soft text-warn"
                        : "border-line-strong bg-surface text-ink-3",
                )}
              >
                {reached ? <IconCheck size={16} /> : i + 1}
              </span>
              <div className="min-w-0 pb-1">
                <p className="font-semibold">
                  {firstName(p.name)} <span className="font-normal text-ink-3">· {p.role === "patient" ? "herself" : p.role === "neighbor" ? "neighbor" : "family (you)"}</span>
                </p>
                {mine.length === 0 ? (
                  <p className="text-sm text-ink-3">{done ? "Not needed" : "Next if needed"}</p>
                ) : (
                  <ul className="space-y-0.5">
                    {mine.map((a) => {
                      const dl = actionDeliveryLabel(a);
                      return (
                        <li key={a.id} className="animate-enter text-sm text-ink-2">
                          <span className="tabular text-ink-3">{fmtTime(a.at, tz)}</span> {CHANNEL_VERB[String(a.data.channel ?? "")] ?? actionHeadline(a, household).split(" ")[0]} ·{" "}
                          <span className={cx("font-semibold", dl.tone === "ok" ? "text-ok" : dl.tone === "warn" ? "text-warn" : "text-ink-3")}>{dl.text}</span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-sm text-ink-3">
        Order set by the family. Alerts stop as soon as the box is taken inside.
      </p>
    </div>
  );
}
