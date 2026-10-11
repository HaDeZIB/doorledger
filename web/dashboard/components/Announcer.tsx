"use client";

import { useEffect, useRef, useState } from "react";
import type { Household, State } from "@/lib/types";
import { actionHeadline, findingLabel } from "@/lib/derive";
import { fmtTime } from "@/lib/time";
import { SEVERITY_STYLE } from "./ui";

/**
 * Screen-reader announcements (visually hidden). One polite region for new findings, new
 * actions and "Right now" headline changes; critical findings go to an assertive region.
 * The visible feeds are NOT live regions (they re-render as a whole and would be read in
 * full). A demo rewind / reset shrinks the record set: resync silently.
 */
export function Announcer({ state, household, headline }: { state: State; household: Household; headline: string }) {
  const tz = household.patient.timezone;
  const [headMsg, setHeadMsg] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [urgent, setUrgent] = useState("");
  const seenF = useRef<Set<string> | null>(null);
  const seenA = useRef<Set<string> | null>(null);
  const lastHead = useRef<string | null>(null);

  useEffect(() => {
    const fIds = new Set(state.findings.map((f) => f.id));
    const aIds = new Set(state.actions.map((a) => a.id));
    if (seenF.current === null || seenA.current === null) {
      seenF.current = fIds;
      seenA.current = aIds;
      return;
    }
    const newF = state.findings.filter((f) => !seenF.current!.has(f.id));
    const newA = state.actions.filter((a) => !seenA.current!.has(a.id));
    seenF.current = fIds;
    seenA.current = aIds;
    if (!newF.length && !newA.length) return;
    const parts = [
      ...newF.map((f) => `${SEVERITY_STYLE[f.severity].label} finding at ${fmtTime(f.at, tz)}: ${findingLabel(f)}. ${f.summary}`),
      ...newA.map((a) => `Action at ${fmtTime(a.at, tz)}: ${actionHeadline(a, household)}.`),
    ];
    setEvents((prev) => [...prev, ...parts].slice(-4)); // a burst (finding + its actions) is read together
    const crit = newF.filter((f) => f.severity === "critical");
    if (crit.length) setUrgent(crit.map((f) => `Urgent: ${findingLabel(f)}. ${f.summary}`).join(" "));
  }, [state.findings, state.actions, household, tz]);

  useEffect(() => {
    if (lastHead.current === null) {
      lastHead.current = headline;
      return;
    }
    if (lastHead.current === headline) return;
    lastHead.current = headline;
    setHeadMsg(`Right now: ${headline}.`);
  }, [headline]);

  // clear after a quiet spell so the same text can be announced again later
  const polite = [headMsg, ...events].filter(Boolean).join(" ");
  useEffect(() => {
    if (!polite && !urgent) return;
    const id = setTimeout(() => {
      setHeadMsg("");
      setEvents([]);
      setUrgent("");
    }, 8000);
    return () => clearTimeout(id);
  }, [polite, urgent]);

  return (
    <>
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {polite}
      </div>
      <div role="alert" aria-live="assertive" aria-atomic="true" className="sr-only">
        {urgent}
      </div>
    </>
  );
}
