"use client";

import type { Scenario } from "@/lib/types";
import type { DoorLedger } from "@/lib/useDoorLedger";
import { SCENARIOS } from "@/lib/mock/script";
import { fmtTimeSec } from "@/lib/time";
import { IconPlay, IconReset, IconX } from "./icons";
import { cx } from "./ui";

const SPEEDS = [1, 10, 30, 60, 120, 300];

export function DemoStrip({ dl, onHide }: { dl: DoorLedger; onHide: () => void }) {
  const tz = dl.household.patient.timezone;
  return (
    <div
      role="region"
      aria-label="Demo controls"
      className="fixed inset-x-2 bottom-2 z-50 mx-auto max-w-5xl rounded-2xl border border-white/10 bg-[#141c25]/95 px-3 py-2.5 text-white shadow-2xl backdrop-blur sm:inset-x-4 sm:bottom-4"
    >
      <div className="flex flex-nowrap items-center gap-2 overflow-x-auto whitespace-nowrap md:flex-wrap">
        <span className="mr-1 inline-flex items-center gap-2 text-sm font-semibold">
          <span className={cx("h-2 w-2 rounded-full", dl.mode === "live" ? "bg-emerald-400" : "bg-amber-300")} />
          {dl.mode === "live" ? "Live API" : "Mock"}
        </span>
        <span className="font-mono text-sm text-white/85 tabular">
          {fmtTimeSec(dl.state.now, tz)}
          {dl.playing && <span className="ml-1 text-amber-300">×{dl.clockSpeed}</span>}
        </span>
        <span className="mx-1 hidden h-5 w-px bg-white/15 sm:block" />
        {(Object.keys(SCENARIOS) as Scenario[]).map((sc) => (
          <button
            key={sc}
            type="button"
            disabled={dl.busy}
            onClick={() => dl.runScenario(sc)}
            title={SCENARIOS[sc].blurb}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-semibold transition disabled:opacity-50",
              dl.playing === sc ? "bg-amber-300 text-[#141c25]" : "bg-white/10 hover:bg-white/20",
            )}
          >
            <IconPlay size={12} /> {SCENARIOS[sc].label}
          </button>
        ))}
        <label className="inline-flex items-center gap-1.5 text-sm text-white/85">
          Speed
          <select
            value={dl.speed}
            onChange={(e) => dl.setSpeed(Number(e.target.value))}
            className="rounded-lg border border-white/15 bg-white/10 px-1.5 py-1 text-sm text-white"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s} className="text-ink">
                {s}×
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={dl.busy}
          onClick={() => dl.reset()}
          className="inline-flex items-center gap-1.5 rounded-xl bg-white/10 px-3 py-1.5 text-sm font-semibold hover:bg-white/20 disabled:opacity-50"
        >
          <IconReset size={14} /> Reset
        </button>
        <div className="ml-auto flex items-center gap-2">
          {dl.mode === "mock" && dl.mockReason === "unreachable" && (
            <button type="button" onClick={() => dl.retryLive()} className="rounded-xl px-2 py-1.5 text-sm text-white/85 underline-offset-2 hover:underline">
              Retry API
            </button>
          )}
          {dl.mode === "live" && (
            <button type="button" onClick={dl.switchToMock} className="rounded-xl px-2 py-1.5 text-sm text-white/85 underline-offset-2 hover:underline">
              Use mock
            </button>
          )}
          <kbd className="hidden rounded border border-white/20 px-1.5 text-xs text-white/70 sm:inline">D</kbd>
          <button type="button" onClick={onHide} aria-label="Hide demo controls" className="rounded-lg p-1.5 hover:bg-white/10">
            <IconX size={16} />
          </button>
        </div>
      </div>
      {dl.liveError && dl.mode === "live" && <p className="mt-1 text-xs text-amber-200">Backend: {dl.liveError}</p>}
    </div>
  );
}
