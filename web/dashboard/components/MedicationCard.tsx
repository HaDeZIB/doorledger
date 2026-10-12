"use client";

import type { DeliveryState, ExposureDirection, ExposureStatus, Household, MedicationProfile, Observation, State } from "@/lib/types";
import {
  LANGUAGE_NAME,
  actionDeliveryLabel,
  actionHeadline,
  actionLanguage,
  actionViaNote,
  actionsForFindings,
  escalationChain,
  findingsFor,
  firstName,
  personFor,
} from "@/lib/derive";
import { DEFAULT_FREEZE_C, exposureDirection, unsafeLimitC } from "@/lib/thermal";
import { fmtClock, fmtDuration, fmtTime, ms } from "@/lib/time";
import { useArrivals } from "@/lib/useArrivals";
import { useUnits } from "@/lib/units";
import { EvidenceFrame } from "./EvidenceFrame";
import { IconCheck, IconClock, IconPackage, IconSnow, IconSun, IconThermo, IconUrgent } from "./icons";
import { Card, CardHeader, LangTag, Pill, SourceBadge, cx } from "./ui";

const CHANNEL_VERB: Record<string, string> = {
  sms: "Texted",
  voice: "Called",
  app: "App alert",
  push: "App alert",
  email: "Emailed",
  telegram: "Messaged",
  whatsapp: "Messaged",
};

type Tone = { chip: string; text: string };
const TONE: Record<"ok" | "cold" | "warn" | "crit", Tone> = {
  ok: { chip: "bg-ok-soft text-ok", text: "text-ok" },
  cold: { chip: "bg-cold-soft text-cold-text", text: "text-cold-text" },
  warn: { chip: "bg-warn-soft text-warn", text: "text-warn" },
  crit: { chip: "bg-crit-soft text-crit", text: "text-crit" },
};

/** Status wording that reads right for both a freezing porch and a hot one. */
function statusCopy(status: ExposureStatus, dir: ExposureDirection): { label: string; tone: Tone } {
  const cold = dir === "cold";
  if (status === "compromised") return { label: cold ? "May have frozen" : dir === "hot" ? "Likely too warm" : "Likely compromised", tone: TONE.crit };
  if (status === "at_risk") return { label: cold ? "Getting too cold" : dir === "hot" ? "Getting too warm" : "At risk", tone: TONE.warn };
  return { label: cold ? "Cold, OK for now" : "Safe for now", tone: cold ? TONE.cold : TONE.ok };
}

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
  const { fmt, alt, both } = useUnits();
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
  const dir = exposureDirection(est, med, household.ambient.celsius);
  const cold = dir === "cold";
  const limitC = unsafeLimitC(est, med, dir);
  const onPorch = Boolean(delivery.dropped && !delivery.removed);
  const inside = Boolean(delivery.removed);
  const sc = est ? statusCopy(est.status, dir) : null;
  const pill =
    inside && est && est.status !== "compromised"
      ? { label: "Inside · est. OK", chip: TONE.ok.chip }
      : inside && est
        ? { label: cold ? "Inside · may have frozen" : "Inside · too warm", chip: TONE.crit.chip }
        : sc && { label: sc.label, chip: sc.tone.chip };

  const title = onPorch ? "Medication on the porch" : inside ? "Medication brought inside" : "Medication delivery expected";
  const findings = findingsFor(state, e.id);
  const actions = actionsForFindings(state, findings);
  const limitText =
    limitC === null || !med ? null : cold ? `Freezing limit ${both(limitC)}` : dir === "hot" ? `Unsafe above ${both(limitC)}` : null;

  return (
    <Card
      aria-labelledby="med-title"
      className={cx(
        "relative overflow-hidden transition-shadow duration-500",
        onPorch && est?.status === "at_risk" && "ring-2 ring-warn-bar/50",
        onPorch && est?.status === "compromised" && "ring-2 ring-crit-bar/50",
      )}
    >
      <CardHeader
        id="med-title"
        eyebrow={
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <IconPackage size={15} /> <span className="truncate">{e.title}</span>
          </span>
        }
        title={title}
        className="xl:pt-3.5"
        titleClassName="xl:text-[1.25rem]"
        right={pill && <Pill className={cx(pill.chip, "transition-colors duration-500")}>{pill.label}</Pill>}
      />
      <p className={cx("px-5 pt-0.5 text-[0.95rem] text-ink-2 sm:px-6", delivery.dropped && "xl:hidden")} title={e.tracking ? `Tracking #${e.tracking}` : undefined}>
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
                  : `We'll watch the porch and start an exposure clock the moment it's left${
                      cold ? `. It's ${fmt(household.ambient.celsius)} outside, so freezing is the risk` : ""
                    }.`}
              </p>
              {med && (
                <p className="mt-1 text-sm text-ink-3">
                  Safe range {fmt(med.freeze_c ?? DEFAULT_FREEZE_C)}–{fmt(med.excursion_max_c)} · fridge {fmt(med.store_min_c)}–{fmt(med.store_max_c)}
                </p>
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 px-5 pt-4 sm:px-6 xl:pt-3">
            {/* exposure clock */}
            <div className="min-w-0 rounded-2xl bg-canvas p-3.5 xl:px-3.5 xl:py-2">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-3">
                <IconClock size={16} /> {inside ? "Time it spent outside" : "Outside for"}
              </p>
              <p
                className={cx(
                  "mt-0.5 font-mono text-[2.1rem] font-bold leading-tight tracking-tight tabular sm:text-[2.6rem] xl:leading-[1.1] xl:text-[2.35rem]",
                  onPorch ? sc?.tone.text : "text-ink",
                )}
                aria-live="off"
              >
                {est ? fmtClock(est.minutes_on_porch) : "--:--"}
              </p>
              <p className="truncate text-[0.95rem] text-ink-2">
                {delivery.removed ? (
                  <span className="tabular" title="Left at the door – taken inside">
                    {fmtTime(delivery.dropped.at, tz)} – {fmtTime(delivery.removed.at, tz)}
                  </span>
                ) : (
                  <>Left at {fmtTime(delivery.dropped.at, tz)}</>
                )}
              </p>
            </div>
            {/* box temperature */}
            <div className="min-w-0 rounded-2xl bg-canvas p-3.5 xl:px-3.5 xl:py-2">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-3">
                <IconThermo size={16} /> Estimated in the box
              </p>
              <p className={cx("mt-0.5 text-[2.1rem] font-bold leading-tight tracking-tight tabular sm:text-[2.6rem] xl:leading-[1.1] xl:text-[2.35rem]", sc?.tone.text)}>
                {est ? (
                  <>
                    <span className="mr-1 align-baseline text-base font-semibold text-ink-3">est.</span>
                    {fmt(est.estimated_internal_c, 1)}
                  </>
                ) : (
                  "—"
                )}
              </p>
              <p className="flex items-center gap-1 text-[0.95rem] text-ink-2">
                {est && (
                  <>
                    {alt(est.estimated_internal_c, 1)} · outside {fmt(est.ambient_c)}
                    {cold ? <IconSnow size={14} className="text-cold" /> : dir === "hot" ? <IconSun size={14} className="text-warn-bar" /> : null}
                  </>
                )}
              </p>
            </div>
          </div>

          {est && med && <ThermoBar internal={est.estimated_internal_c} med={med} dir={dir} moving={onPorch} />}

          <div className="px-5 sm:px-6">
            <Countdown delivery={delivery} dir={dir} limitText={limitText} />
          </div>

          <div className="grid gap-4 px-5 pb-5 pt-4 sm:grid-cols-[1fr_1.1fr] sm:px-6 xl:grid-cols-[0.8fr_1.2fr] xl:gap-3 xl:pb-3.5 xl:pt-2.5">
            <div className="min-w-0">
              <p className="mb-1.5 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">Proof</p>
              <EvidenceFrame
                obs={delivery.removed ?? delivery.dropped}
                url={evidenceUrl(delivery.removed ?? delivery.dropped)}
                alternates={delivery.removed ? [{ obs: delivery.dropped, url: evidenceUrl(delivery.dropped) }] : []}
                tz={tz}
                wideOverlay
              />
              {delivery.removed && !evidenceUrl(delivery.removed) && (
                <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2 xl:hidden">
                  <span>
                    Taken inside <span className="tabular">{fmtTime(delivery.removed.at, tz)}</span>
                  </span>
                  <SourceBadge source={delivery.removed.source} />
                  {delivery.removed.source === "simulated" && <span className="text-ink-3">no camera frame yet</span>}
                </p>
              )}
            </div>
            <Escalation household={household} actions={actions} tz={tz} done={inside} />
          </div>
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------------
// Thermometer: freezing ← cool ← FRIDGE → warm → too hot. Piecewise scale so the fridge range
// and both limits stay readable whichever way the box is drifting.

function ThermoBar({ internal, med, dir, moving }: { internal: number; med: MedicationProfile; dir: ExposureDirection; moving: boolean }) {
  const { fmt, both } = useUnits();
  const freeze = med.freeze_c ?? DEFAULT_FREEZE_C;
  const stops: [number, number][] = [
    [freeze - 10, 0],
    [freeze, 16],
    [med.store_min_c, 25],
    [med.store_max_c, 53],
    [med.excursion_max_c, 84],
    [med.excursion_max_c + 8, 100],
  ];
  const pos = (c: number) => {
    if (c <= stops[0][0]) return 0;
    for (let i = 1; i < stops.length; i++) {
      const [c1, p1] = stops[i];
      const [c0, p0] = stops[i - 1];
      if (c <= c1) return p0 + ((c - c0) / (c1 - c0)) * (p1 - p0);
    }
    return 100;
  };
  const zones = [
    { from: 0, to: 16, cls: "bg-zone-freeze" },
    { from: 16, to: 25, cls: "bg-zone-cool" },
    { from: 25, to: 53, cls: "bg-zone-fridge" },
    { from: 53, to: 84, cls: "bg-zone-warm" },
    { from: 84, to: 100, cls: "bg-zone-hot" },
  ];
  const p = Math.max(0, Math.min(100, pos(internal)));
  const cold = dir === "cold";
  const hot = dir === "hot";
  const inFridge = internal >= med.store_min_c && internal <= med.store_max_c;
  // drift direction while it's still outside: ← cooling toward freezing, → warming
  const arrow = moving && cold ? "← " : "";
  const arrowAfter = moving && hot ? " →" : "";
  return (
    <div
      className="px-5 pt-3 sm:px-6 xl:pt-2"
      role="img"
      aria-label={`Estimated ${both(internal, 1)} in the box. Fridge range ${fmt(med.store_min_c)} to ${fmt(med.store_max_c)}. Freezes at ${both(freeze)}; too hot above ${both(med.excursion_max_c)}.`}
    >
      {/* marker bubble */}
      <div className="relative h-7 xl:h-6">
        <div
          className={cx(
            "absolute bottom-1 -translate-x-1/2 whitespace-nowrap rounded-full px-2 py-0.5 text-[0.78rem] font-bold text-white shadow-sm transition-[left] duration-700 ease-out tabular",
            inFridge ? "bg-ok" : cold || internal < med.store_min_c ? "bg-cold-text" : "bg-warn",
          )}
          style={{ left: `clamp(2.2rem, ${p}%, calc(100% - 2.2rem))` }}
        >
          {arrow}box est. {fmt(internal, 0)}
          {arrowAfter}
        </div>
      </div>
      <div className="relative h-3.5 overflow-hidden rounded-full ring-1 ring-inset ring-ink/5">
        {zones.map((z) => (
          <div key={z.from} className={cx("absolute inset-y-0", z.cls)} style={{ left: `${z.from}%`, width: `${z.to - z.from}%` }} />
        ))}
        {/* limit ticks */}
        <div className={cx("absolute inset-y-0 w-0.5 -translate-x-1/2", cold ? "bg-cold-text" : "bg-cold/40")} style={{ left: "16%" }} />
        <div className={cx("absolute inset-y-0 w-0.5 -translate-x-1/2", hot ? "bg-crit" : "bg-crit/30")} style={{ left: "84%" }} />
      </div>
      <div className="relative h-0">
        <div
          className="absolute -top-[1.19rem] h-6 w-1.5 -translate-x-1/2 rounded-full bg-ink shadow ring-2 ring-surface transition-[left] duration-700 ease-out"
          style={{ left: `${p}%` }}
        />
      </div>
      <div className="relative mt-1.5 h-7 text-[0.75rem] leading-[1.1] sm:h-4 sm:leading-none">
        <span className={cx("absolute -translate-x-1/2 whitespace-nowrap text-center", cold ? "font-bold text-cold-text" : "text-ink-3")} style={{ left: "16%" }}>
          Freezes
          <br className="sm:hidden" /> <span className="tabular">{fmt(freeze)}</span>
        </span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap text-center font-medium text-ok" style={{ left: "39%" }}>
          Fridge
          <br className="sm:hidden" />{" "}
          <span className="tabular">
            {fmt(med.store_min_c)}–{fmt(med.store_max_c)}
          </span>
        </span>
        <span className={cx("absolute -translate-x-1/2 whitespace-nowrap text-center", hot ? "font-bold text-crit" : "text-ink-3")} style={{ left: "84%" }}>
          Too hot
          <br className="sm:hidden" /> <span className="tabular">{fmt(med.excursion_max_c)}</span>
        </span>
      </div>
    </div>
  );
}

function Countdown({ delivery, dir, limitText }: { delivery: DeliveryState; dir: ExposureDirection; limitText: string | null }) {
  const { fmt, alt } = useUnits();
  const est = delivery.estimate;
  if (!est) return null;
  const cold = dir === "cold";
  const sub = limitText && <p className="text-sm font-medium opacity-90">{limitText}</p>;
  if (delivery.removed) {
    const simulatedPickup = delivery.removed.source === "simulated";
    const pickupSub = (
      <p className="flex flex-wrap items-center gap-x-1.5 text-sm font-medium opacity-90">
        {limitText}
        {simulatedPickup && (
          <>
            {limitText && <span aria-hidden>·</span>}
            <span>pickup</span>
            <SourceBadge source="simulated" className="!py-0 text-[0.72rem]" />
          </>
        )}
      </p>
    );
    const ok = est.status !== "compromised";
    return (
      <div className={cx("mt-2 flex items-center gap-3 rounded-2xl px-4 py-2 animate-swap", ok ? "bg-ok-soft text-ok" : "bg-crit-soft text-crit")}>
        {ok ? <IconCheck size={22} className="shrink-0" /> : <IconUrgent size={22} className="shrink-0" />}
        <div className="min-w-0 flex-1">
          <p className="text-[1.05rem] font-semibold leading-snug xl:text-[1rem]">
            {ok
              ? cold
                ? "Estimated to have stayed above freezing."
                : "Estimated to have stayed under the unsafe limit."
              : cold
                ? "Brought inside, but it may have frozen. Frozen insulin must be thrown away; call the pharmacy for a replacement."
                : "Brought inside, but it likely got too warm. Call the pharmacy before using it."}
          </p>
          {pickupSub}
        </div>
      </div>
    );
  }
  if (est.status === "compromised") {
    return (
      <div className="mt-2 flex items-center gap-3 rounded-2xl bg-crit-soft px-4 py-2 text-crit">
        {cold && <IconSnow size={22} className="shrink-0" />}
        <div>
          <p className="text-[1.05rem] font-semibold leading-snug">
            {cold
              ? "May have frozen. Don't use it: frozen insulin must be thrown away. Call the pharmacy."
              : "Past the safe limit. Don't use it until the pharmacy says it's OK."}
          </p>
          {sub}
        </div>
      </div>
    );
  }
  const left = est.minutes_until_excursion_max;
  const risk = est.status === "at_risk";
  const headline =
    left === null
      ? cold
        ? "Not expected to freeze at today's temperature"
        : dir === "hot"
          ? "Not expected to overheat at today's temperature"
          : "Fine at today's temperature"
      : risk
        ? cold
          ? "Getting too cold! Bring it in now"
          : "Getting too warm! Bring it in now"
        : cold
          ? "Getting colder. Bring it in soon"
          : "Needs to come inside soon";
  return (
    <div
      key={risk ? "risk" : "safe"}
      className={cx(
        "mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-2xl px-4 py-2",
        risk ? "bg-warn-soft text-warn animate-flash" : cold ? "bg-cold-soft text-cold-text" : "bg-ok-soft text-ok",
      )}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        {cold && <IconSnow size={20} className="shrink-0" />}
        <div className="min-w-0">
          <p className="text-[1.05rem] font-semibold leading-snug">{headline}</p>
          {sub}
        </div>
      </div>
      {left !== null && (
        <p className="flex flex-col items-end whitespace-nowrap text-right leading-tight tabular">
          <span className="text-sm font-medium">{cold ? "est. freezes in" : "est. unsafe in"}</span>
          <span className="text-2xl font-bold">{fmtDuration(left)}</span>
        </p>
      )}
    </div>
  );
}

function Escalation({ household, actions, tz, done }: { household: Household; actions: State["actions"]; tz: string; done: boolean }) {
  const chain = escalationChain(household);
  const isNew = useArrivals(actions.map((a) => a.id));
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-sm font-semibold uppercase tracking-[0.08em] text-ink-3" title="Order set by the family. Alerts stop once it's inside.">
        Who we&apos;ve contacted
      </p>
      <ol className="relative space-y-2.5 xl:space-y-1">
        {chain.map((p, i) => {
          const mine = actions.filter((a) => personFor(household, a.target)?.name === p.name);
          // reached = they answered/replied; contacted = message delivered; unanswered = only failed attempts
          const reached = mine.some((a) => Boolean(a.data.reply) || a.data.status === "answered");
          const contacted = mine.some((a) => a.delivered);
          const tried = mine.length > 0;
          return (
            <li key={p.name} className="relative flex gap-3">
              {i < chain.length - 1 && <span className="absolute left-[calc(1rem-1px)] top-8 h-[calc(100%-12px)] w-0.5 bg-line xl:left-[calc(0.875rem-1px)] xl:top-7" aria-hidden />}
              <span
                className={cx(
                  "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors duration-500 xl:h-7 xl:w-7",
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
                {mine.some((a) => isNew(a.id)) && <span className="pointer-events-none absolute inset-0 rounded-full bg-brand/40 animate-ping-once" aria-hidden />}
              </span>
              <div className="min-w-0 pb-0.5">
                <p className="font-semibold leading-snug">
                  {firstName(p.name)}{" "}
                  <span className="font-normal text-ink-3">· {p.role === "patient" ? "herself" : p.role === "neighbor" ? "neighbor" : "family (you)"}</span>
                  {mine.length === 0 && (
                    <span className="hidden text-[0.82rem] font-normal text-ink-3 xl:inline"> · {done ? "not needed" : "next if needed"}</span>
                  )}
                </p>
                {mine.length === 0 ? (
                  <p className="text-sm text-ink-3 xl:hidden">{done ? "Not needed" : "Next if needed"}</p>
                ) : (
                  <ul className="space-y-0.5">
                    {mine.map((a, k) => {
                      const dl = actionDeliveryLabel(a);
                      const lang = actionLanguage(a);
                      return (
                        <li
                          key={a.id}
                          title={actionViaNote(a) ?? undefined}
                          className={cx(
                            "flex flex-wrap items-center gap-x-1.5 text-sm text-ink-2 xl:text-[0.82rem]",
                            k < mine.length - 1 && "xl:hidden", // wide screens: latest message only
                            isNew(a.id) ? "animate-enter" : "",
                          )}
                        >
                          <span className="tabular text-ink-3">{fmtTime(a.at, tz)}</span>
                          <span>{CHANNEL_VERB[String(a.data.channel ?? "")] ?? actionHeadline(a, household).split(" ")[0]}</span>
                          {lang && <LangTag code={lang} title={LANGUAGE_NAME[lang] ? `Message in ${LANGUAGE_NAME[lang]}` : undefined} />}
                          <span aria-hidden className={cx(dl.text === "Delivered" && "xl:hidden")}>
                            ·
                          </span>
                          <span
                            className={cx(
                              "font-semibold",
                              dl.tone === "ok" ? "text-ok" : dl.tone === "warn" ? "text-warn" : "text-ink-3",
                              dl.text === "Delivered" && "xl:sr-only",
                            )}
                          >
                            {dl.text}
                          </span>
                          {dl.text === "Delivered" && <IconCheck size={14} className="hidden text-ok xl:inline" aria-hidden />}
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
      <p className="mt-2.5 text-[0.8rem] text-ink-3 xl:hidden">Order set by the family. Alerts stop once it&apos;s inside.</p>
    </div>
  );
}
