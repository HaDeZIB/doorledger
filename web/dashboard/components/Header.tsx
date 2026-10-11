"use client";

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
  replay: "Replay",
};

const AMBIENT_SRC: Record<Household["ambient"]["source"], string> = {
  "open-meteo": "Open-Meteo",
  override: "manual",
  fallback: "estimate",
};

export function Header({
  household,
  tab,
  onTab,
  mode,
  streamConnected,
}: {
  household: Household;
  tab: Tab;
  onTab: (t: Tab) => void;
  mode: Mode;
  streamConnected: boolean;
}) {
  const { fmt, alt, unit, setUnit } = useUnits();
  const d = household.device;
  const online = d.online;
  return (
    <>
    <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-white">
            <IconLogo size={22} />
          </span>
          <span className="text-lg font-bold tracking-tight">DoorLedger</span>
        </div>
        <nav aria-label="Views" className="order-last flex w-full rounded-2xl bg-canvas p-1 sm:order-none sm:w-auto">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
              className={cx(
                "flex-1 rounded-xl px-3 py-1.5 text-[0.95rem] font-semibold transition sm:flex-none sm:px-4",
                tab === t.id ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink",
              )}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
    </header>

    <div className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 pb-5 pt-4 sm:px-6">
        <div className="min-w-0">
          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-tight sm:text-3xl">
            {household.patient.name}, {household.patient.age}
          </h1>
          <p className="truncate text-ink-3">{household.patient.address}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cx(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold",
              online === true && "border-ok-bar/30 bg-ok-soft text-ok",
              online === false && "border-crit-bar/30 bg-crit-soft text-crit",
              online === null && "border-line-strong bg-canvas text-ink-2",
            )}
            title={`Ring doorbell “${d.name}” (${d.id})`}
          >
            <span className={cx("h-2 w-2 rounded-full", online === true ? "bg-ok-bar animate-pulse-ring text-ok-bar" : online === false ? "bg-crit-bar" : "bg-ink-3")} />
            Ring doorbell <span className="hidden sm:inline">· {d.name}</span> · {online === true ? "Online" : online === false ? "Offline" : "Unknown"}
            <span className="rounded-md bg-surface/80 px-1.5 py-px text-[0.72rem] font-bold uppercase tracking-wide text-ink-2">{SOURCE_BADGE[d.source]}</span>
          </span>
          <button
            type="button"
            onClick={() => setUnit(unit === "F" ? "C" : "F")}
            className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 py-1.5 text-sm font-semibold text-ink-2 hover:border-ink-3"
            title={`Outside temperature (${AMBIENT_SRC[household.ambient.source]}). Click to switch °F/°C.`}
            aria-label={`Outside ${fmt(household.ambient.celsius)}, ${alt(household.ambient.celsius)}. Switch units.`}
          >
            <IconThermo size={16} />
            <span className="tabular">{fmt(household.ambient.celsius)}</span>
            <span className="font-normal text-ink-3">outside · {AMBIENT_SRC[household.ambient.source]}</span>
          </button>
          {mode === "live" && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-sm font-semibold text-ink-2" title="Live ledger stream">
              <span className={cx("h-2 w-2 rounded-full", streamConnected ? "bg-ok-bar" : "bg-warn-bar")} />
              {streamConnected ? "Live" : "Reconnecting…"}
            </span>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
