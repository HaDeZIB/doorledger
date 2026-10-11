"use client";

import type { Household, State } from "@/lib/types";
import { firstName, visitStatus } from "@/lib/derive";
import { fmtDuration, fmtTime, ms } from "@/lib/time";
import { useUnits } from "@/lib/units";
import { exposureDirection } from "@/lib/thermal";
import { IconAlert, IconCheck, IconPackage, IconSnow, IconUser } from "./icons";
import { cx } from "./ui";

type Tone = "ok" | "warn" | "crit" | "calm";

/** One sentence that answers "is Mom OK right now?" before anything else. */
export function StatusBanner({ state, household }: { state: State; household: Household }) {
  const tz = household.patient.timezone;
  const { fmt } = useUnits();
  const name = firstName(household.patient.name);
  const now = ms(state.now);

  let tone: Tone = "ok";
  let icon = IconCheck;
  let head = "";
  let sub = "";

  const porch = state.deliveries.find((d) => d.dropped && !d.removed);
  const missed = state.visits.find((v) => visitStatus(v, state.now, state.findings).key === "missed" && now <= ms(v.expectation.window_end) + 90 * 60000);
  const late = state.visits.find((v) => visitStatus(v, state.now, state.findings).key === "late");
  const inProg = state.visits.find((v) => visitStatus(v, state.now, state.findings).key === "in_progress");

  if (porch?.estimate) {
    const e = porch.estimate;
    const dir = exposureDirection(e, porch.expectation.medication, household.ambient.celsius);
    const cold = dir === "cold";
    const what = porch.expectation.medication?.name.split(" ")[0].toLowerCase() ?? "medication";
    tone = e.status === "safe" ? "warn" : "crit";
    icon = cold ? IconSnow : IconPackage;
    head =
      e.status === "compromised"
        ? cold
          ? `${name}'s ${what} may have frozen on the porch`
          : `${name}'s ${what} likely got too warm on the porch`
        : e.status === "at_risk" && cold
          ? `${name}'s ${what} is getting too cold on the porch`
          : `${name}'s ${what} is on the porch${cold ? ` in ${fmt(e.ambient_c)} cold` : ""}`;
    sub =
      e.status === "compromised"
        ? `Out ${fmtDuration(e.minutes_on_porch)}; estimated ${fmt(e.estimated_internal_c)} inside the box.${cold ? " Frozen insulin must be thrown away." : ""}`
        : `Out ${fmtDuration(e.minutes_on_porch)} · estimated ${fmt(e.estimated_internal_c, 1)} inside the box${
            e.minutes_until_excursion_max !== null ? ` · ${cold ? "freezes" : "unsafe"} in ${fmtDuration(e.minutes_until_excursion_max)}` : ""
          }. We're handling it.`;
  } else if (missed) {
    tone = "crit";
    icon = IconAlert;
    head = `${missed.expectation.title} didn't happen`;
    sub = state.actions.some((a) => a.kind === "request_backup") ? "We've asked the agency for a backup aide." : "We're contacting the agency.";
  } else if (late) {
    tone = "warn";
    icon = IconUser;
    head = `${firstName(late.expectation.caregiver ?? "The aide")} is late for the ${fmtTime(late.expectation.window_start, tz)} visit`;
    sub = "The agency has been told. We'll update you when she checks in.";
  } else if (inProg) {
    tone = "calm";
    icon = IconUser;
    const who = (inProg.check_in?.detail.caregiver as string | undefined) ?? inProg.expectation.caregiver ?? "The aide";
    head = `${firstName(who)} is with ${name} now`;
    const so = inProg.minutes_on_site ?? Math.max(0, Math.round((now - ms(inProg.check_in!.at)) / 60000));
    sub = `Checked in at ${fmtTime(inProg.check_in!.at, tz)} · ${so} of ${inProg.expectation.planned_minutes} min so far.`;
  } else {
    const upcoming = [...state.visits.map((v) => v.expectation), ...state.deliveries.filter((d) => !d.dropped).map((d) => d.expectation)]
      .filter((e) => ms(e.window_start) > now)
      .sort((a, b) => ms(a.window_start) - ms(b.window_start))[0];
    const issues = state.findings.filter((f) => f.severity !== "info").length;
    head = issues ? "All clear right now" : "Everything expected so far has arrived";
    sub = upcoming ? `Next: ${upcoming.title} at ${fmtTime(upcoming.window_start, tz)}.` : "Nothing else is scheduled today.";
    if (issues) sub = `${issues} earlier issue${issues > 1 ? "s" : ""} handled today. ${sub}`;
  }

  const Icon = icon;
  const styles: Record<Tone, string> = {
    ok: "bg-ok-soft border-ok-bar/30 text-ok",
    calm: "bg-brand-soft border-brand/25 text-brand-strong",
    warn: "bg-warn-soft border-warn-bar/40 text-warn",
    crit: "bg-crit-soft border-crit-bar/40 text-crit",
  };

  return (
    <section aria-live="polite" aria-label="Right now" className={cx("flex items-start gap-4 rounded-3xl border px-5 py-4 transition-colors duration-500 sm:items-center sm:px-6 lg:py-3 xl:py-2.5", styles[tone])}>
      <span className="relative mt-0.5 flex h-11 w-11 xl:h-10 xl:w-10 shrink-0 items-center justify-center rounded-2xl bg-surface/80 sm:mt-0">
        <Icon size={24} />
        {(tone === "warn" || tone === "crit") && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-current animate-pulse-ring" />}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold uppercase tracking-[0.08em] opacity-90 lg:sr-only">Right now</p>
        <p key={head} className="animate-enter text-xl font-semibold leading-snug text-ink sm:text-2xl lg:text-[1.4rem] xl:text-[1.3rem]">{head}</p>
        <p className="mt-0.5 text-ink-2 xl:text-[0.97rem]">{sub}</p>
      </div>
    </section>
  );
}
