"use client";

import { useRef } from "react";
import type { Household } from "@/lib/types";
import type { Mode } from "@/lib/useDoorLedger";
import { useUnits } from "@/lib/units";
import { IconLogo, IconThermo } from "./icons";
import { cx } from "./ui";

export type Tab = "today" | "agency" | "ledger";

const TABS: { id: Tab; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "agency", label: "Agency" },
  { id: "ledger", label: "Ledger" },
];

const SOURCE_BADGE: Record<Household["device"]["source"], string> = {
  ring_playground: "Ring Playground",
  ring_api: "Ring API",
  replay: "Demo replay",
};

export const tabId = (t: Tab) => `tab-${t}`;
export const panelId = (t: Tab) => `panel-${t}`;

const AMBIENT_SRC: Record<Household["ambient"]["source"], string> = {
  "open-meteo": "Open-Meteo",
  override: "manual",
  fallback: "estimate",
  scenario: "scripted scenario",
};

export function Header({
  household,
  tab,
  onTab,
  mode,
  streamConnected,
  demoNote,
}: {
  household: Household;
  tab: Tab;
  onTab: (t: Tab) => void;
  mode: Mode;
  streamConnected: boolean;
  /** Short "demo data" chip shown in the header on wide screens (mock mode). */
  demoNote?: string | null;
}) {
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ today: null, agency: null, ledger: null });
  // WAI-ARIA tabs: roving tabindex, ←/→ (wrapping), Home/End move focus AND select (automatic activation)
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const i = TABS.findIndex((t) => t.id === tab);
    let j = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % TABS.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = TABS.length - 1;
    if (j < 0) return;
    e.preventDefault();
    const next = TABS[j].id;
    onTab(next);
    tabRefs.current[next]?.focus();
  };
  const nav = (
    <div role="tablist" aria-label="Views" aria-orientation="horizontal" onKeyDown={onKeyDown} className="flex w-full rounded-2xl bg-canvas p-1 sm:w-auto">
      {TABS.map((t) => {
        const selected = tab === t.id;
        return (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[t.id] = el;
            }}
            id={tabId(t.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={panelId(t.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onTab(t.id)}
            className={cx(
              "flex-1 rounded-xl px-3 py-1.5 text-[0.95rem] font-semibold transition sm:flex-none sm:px-4",
              selected ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
  return (
    <>
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 sm:px-6 xl:py-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand text-white">
              <IconLogo size={22} />
            </span>
            <span className="text-lg font-bold tracking-tight">DoorLedger</span>
            {/* wide screens: patient in the same row */}
            <span className="mx-2 hidden h-8 w-px bg-line xl:block" aria-hidden />
            <div className="hidden min-w-0 xl:block">
              <p className="truncate text-[1.2rem] font-semibold leading-tight tracking-tight">
                {household.patient.name}, {household.patient.age}
              </p>
              <p className="truncate text-sm leading-tight text-ink-3">{household.patient.address}</p>
            </div>
          </div>
          <div className="hidden items-center gap-2 xl:flex">
            <StatusChips household={household} mode={mode} streamConnected={streamConnected} compact note={demoNote} />
            {/* the device chip already says "Demo replay" for a replayed doorbell */}
            {demoNote && household.device.source !== "replay" && (
              <span className="rounded-full border border-dashed border-line-strong px-2.5 py-1 text-[0.8rem] font-semibold text-ink-3" title={demoNote}>
                Demo data
              </span>
            )}
          </div>
          <div className="order-last w-full sm:order-none sm:w-auto">{nav}</div>
        </div>
      </header>

      <div className="border-b border-line bg-surface xl:hidden">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 pb-5 pt-4 sm:px-6">
          <div className="min-w-0">
            <h1 className="text-[1.75rem] font-semibold leading-tight tracking-tight sm:text-3xl">
              {household.patient.name}, {household.patient.age}
            </h1>
            <p className="truncate text-ink-3">{household.patient.address}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusChips household={household} mode={mode} streamConnected={streamConnected} />
          </div>
        </div>
      </div>
      {/* one h1 for assistive tech on wide screens too */}
      <h1 className="sr-only hidden xl:block">
        {household.patient.name}, {household.patient.age}
      </h1>
    </>
  );
}

function StatusChips({
  household,
  mode,
  streamConnected,
  compact = false,
  note,
}: {
  household: Household;
  mode: Mode;
  streamConnected: boolean;
  compact?: boolean;
  note?: string | null;
}) {
  const { fmt, alt, unit, setUnit } = useUnits();
  const d = household.device;
  const online = d.online;
  return (
    <>
      <span
        className={cx(
          "inline-flex items-center gap-2 whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-semibold",
          online === true && "border-ok-bar/30 bg-ok-soft text-ok",
          online === false && "border-crit-bar/30 bg-crit-soft text-crit",
          online === null && "border-line-strong bg-canvas text-ink-2",
        )}
        title={`Ring doorbell “${d.name}” (${d.id}) · ${online === null ? "online status not reported" : online ? "online" : "offline"} · ${SOURCE_BADGE[d.source]}${note ? `. ${note}` : ""}`}
      >
        <span className={cx("h-2 w-2 rounded-full", online === true ? "bg-ok-bar animate-pulse-ring text-ok-bar" : online === false ? "bg-crit-bar" : "bg-ink-3")} />
        Ring doorbell <span className={cx(compact ? "hidden" : "hidden sm:inline")}>· {d.name}</span>
        {/* unknown online status: say so in full width, but don't spend header space on it when compact */}
        {online === true ? " · Online" : online === false ? " · Offline" : compact ? <span className="sr-only"> · online status unknown</span> : <span className="font-medium"> · status unknown</span>}
        <span className="rounded-md bg-surface/80 px-1.5 py-px text-[0.72rem] font-bold uppercase tracking-wide text-ink-2">{SOURCE_BADGE[d.source]}</span>
      </span>
      <button
        type="button"
        onClick={() => setUnit(unit === "F" ? "C" : "F")}
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line-strong bg-surface px-3 py-1.5 text-sm font-semibold text-ink-2 hover:border-ink-3"
        title={`Outside temperature (${AMBIENT_SRC[household.ambient.source]}). Click to switch °F/°C.`}
        aria-label={`Outside ${fmt(household.ambient.celsius)}, ${alt(household.ambient.celsius)}. Switch units.`}
      >
        <IconThermo size={16} />
        <span className="tabular">{fmt(household.ambient.celsius)}</span>
        {/* live mode adds a third chip: drop the other unit there so the header stays one row at 1280 px */}
        <span className={cx("font-normal tabular text-ink-3", compact && mode === "live" && "hidden")}>({alt(household.ambient.celsius)})</span>
        <span className={cx("font-normal text-ink-3", compact && "hidden")}>outside · {AMBIENT_SRC[household.ambient.source]}</span>
        {compact && <span className="font-normal text-ink-3">outside</span>}
      </button>
      {mode === "live" && (
        <span
          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line-strong px-3 py-1.5 text-sm font-semibold text-ink-2"
          title="Connection to the DoorLedger backend's live update stream (not the camera)"
        >
          <span className={cx("h-2 w-2 rounded-full", streamConnected ? "bg-ok-bar" : "bg-warn-bar")} aria-hidden />
          {streamConnected ? "Live updates" : "Reconnecting…"}
        </span>
      )}
    </>
  );
}
