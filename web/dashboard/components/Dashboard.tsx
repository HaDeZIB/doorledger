"use client";

import { useEffect, useState } from "react";
import { featuredDelivery, featuredVisit, findingLabel } from "@/lib/derive";
import { UnitsProvider } from "@/lib/units";
import { useDoorLedger, type InitialData } from "@/lib/useDoorLedger";
import { AgencyView } from "./AgencyView";
import { AskCard, SummaryCard } from "./AskPanel";
import { DayTimeline } from "./DayTimeline";
import { DemoStrip } from "./DemoStrip";
import { ActionsFeed, FindingsFeed } from "./Feeds";
import { Header, type Tab } from "./Header";
import { IconX } from "./icons";
import { LedgerView } from "./LedgerView";
import { MedicationCard } from "./MedicationCard";
import { StatusBanner } from "./StatusBanner";
import { SEVERITY_STYLE, cx } from "./ui";
import { VisitCard } from "./VisitCard";

const DEMO_KEY = "doorledger.demoStrip";

export function Dashboard({ initial }: { initial: InitialData }) {
  return (
    <UnitsProvider>
      <DashboardInner initial={initial} />
    </UnitsProvider>
  );
}

function DashboardInner({ initial }: { initial: InitialData }) {
  const dl = useDoorLedger(initial);
  const [tab, setTab] = useState<Tab>("today");
  const [demo, setDemo] = useState(true);
  const tz = dl.household.patient.timezone;

  useEffect(() => {
    try {
      const pref = localStorage.getItem(DEMO_KEY);
      // hidden by default on phones; remembered once toggled
      if (pref === "0" || (pref === null && window.innerWidth < 640)) setDemo(false);
      const h = window.location.hash.replace("#", "");
      if (h === "agency" || h === "ledger" || h === "today") setTab(h);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "d" || e.key === "D") {
        setDemo((v) => {
          try {
            localStorage.setItem(DEMO_KEY, v ? "0" : "1");
          } catch {
            /* ignore */
          }
          return !v;
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const changeTab = (t: Tab) => {
    setTab(t);
    try {
      history.replaceState(null, "", t === "today" ? window.location.pathname : `#${t}`);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="min-h-screen pb-28">
      <Header household={dl.household} tab={tab} onTab={changeTab} mode={dl.mode} streamConnected={dl.streamConnected} />

      {dl.mode === "mock" && (
        <div className="mx-auto max-w-6xl px-4 pt-4 sm:px-6">
          <p className="rounded-2xl border border-dashed border-line-strong bg-surface/60 px-4 py-2 text-sm text-ink-2">
            <strong className="font-semibold text-ink">Demo data.</strong>{" "}
            {dl.mockReason === "unreachable"
              ? "The DoorLedger backend isn't reachable, so this page is playing a recorded day for a fictional household."
              : "Playing a recorded day for a fictional household."}{" "}
            <span className="hidden sm:inline">Press D for demo controls.</span>
          </p>
        </div>
      )}

      <main className="mx-auto max-w-6xl space-y-6 px-4 pt-5 sm:px-6">
        {tab === "today" && (
          <>
            <StatusBanner state={dl.state} household={dl.household} />
            <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
              <AskCard key={`ask-${dl.mode}`} household={dl.household} mode={dl.mode} ask={dl.ask} />
              <SummaryCard key={`sum-${dl.mode}`} mode={dl.mode} summarize={dl.summarize} />
            </div>
            <DayTimeline household={dl.household} state={dl.state} timeline={dl.timeline} observations={dl.observations} evidenceUrl={dl.evidenceUrl} />
            <div className="grid gap-6 lg:grid-cols-2">
              <MedicationCard delivery={featuredDelivery(dl.state)} household={dl.household} state={dl.state} evidenceUrl={dl.evidenceUrl} />
              <VisitCard visit={featuredVisit(dl.state)} household={dl.household} state={dl.state} evidenceUrl={dl.evidenceUrl} />
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <FindingsFeed state={dl.state} observations={dl.observations} tz={tz} />
              <ActionsFeed state={dl.state} household={dl.household} tz={tz} />
            </div>
          </>
        )}
        {tab === "agency" && <AgencyView state={dl.state} household={dl.household} onExport={dl.exportEvv} />}
        {tab === "ledger" && <LedgerView timeline={dl.timeline} household={dl.household} />}
      </main>

      <footer className="mx-auto mt-12 max-w-6xl px-4 text-center text-ink-3 sm:px-6">
        <p className="text-lg font-semibold text-ink-2">Care is delivered through the front door. DoorLedger makes sure it arrived.</p>
        <p className="mt-1 text-sm">
          No face recognition. Aides check in with a rotating code shown to the Ring doorbell. Temperatures are estimates from a thermal model, not a
          thermometer.
        </p>
      </footer>

      {/* toasts */}
      <div className="pointer-events-none fixed right-3 top-3 z-[60] flex w-[min(24rem,calc(100vw-1.5rem))] flex-col gap-2" aria-live="assertive">
        {dl.toasts.map((t) => {
          const s = SEVERITY_STYLE[t.finding.severity];
          const Icon = s.icon;
          return (
            <div key={t.id} className={cx("pointer-events-auto animate-enter flex items-start gap-3 rounded-2xl border border-line bg-surface p-3.5 shadow-xl")}>
              <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", s.chip)}>
                <Icon size={17} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{findingLabel(t.finding)}</p>
                <p className="text-sm text-ink-2">{t.finding.summary}</p>
              </div>
              <button type="button" onClick={() => dl.dismissToast(t.id)} aria-label="Dismiss" className="rounded-lg p-1 text-ink-3 hover:bg-canvas">
                <IconX size={16} />
              </button>
            </div>
          );
        })}
      </div>

      {demo && <DemoStrip
          dl={dl}
          onHide={() => {
            setDemo(false);
            try {
              localStorage.setItem(DEMO_KEY, "0");
            } catch {
              /* ignore */
            }
          }}
        />}
    </div>
  );
}
