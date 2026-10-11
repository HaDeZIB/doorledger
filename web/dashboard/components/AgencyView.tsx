"use client";

import type { Household, State, VisitState } from "@/lib/types";
import { isDoorVerified, visitStatus } from "@/lib/derive";
import { dateIn, fmtDateLong, fmtTime, ms } from "@/lib/time";
import { IconCheck, IconDownload, IconFlask, IconShield, IconX } from "./icons";
import { Card, CardHeader, SourceBadge, StatusChip, cx } from "./ui";

const EVV_FIELDS = [
  "Type of service",
  "Individual receiving the service",
  "Date of service",
  "Location of service",
  "Individual providing the service",
  "Time service begins and ends",
];

/**
 * EVV completeness. Elements 5 (who provided it) and 6 (begin/end time) are only captured
 * when presence was verified at the door (signed code in a camera frame). Simulated or
 * unverified check-ins leave them open.
 */
function evvFields(v: VisitState): boolean[] {
  const e = v.expectation;
  const provider = Boolean((v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver);
  const inOk = isDoorVerified(v.check_in);
  const outOk = isDoorVerified(v.check_out);
  return [true, true, true, true, provider && inOk, inOk && outOk];
}

/** A visit is "verified at the door" only if BOTH check-in and check-out are door-verified. */
const visitVerified = (v: VisitState) => isDoorVerified(v.check_in) && isDoorVerified(v.check_out);
const visitSimulated = (v: VisitState) => [v.check_in, v.check_out].some((o) => o?.source === "simulated");

export function AgencyView({ state, household, onExport }: { state: State; household: Household; onExport: () => void }) {
  const tz = household.patient.timezone;
  const visits = [...state.visits].sort((a, b) => ms(a.expectation.window_start) - ms(b.expectation.window_start));
  const statuses = visits.map((v) => visitStatus(v, state.now, state.findings));
  const verified = visits.filter(visitVerified).length;
  const simulated = visits.filter(visitSimulated).length;
  const exceptions = statuses.filter((s) => s.key === "short" || s.key === "missed" || s.key === "late").length;
  const backups = visits.filter((v) => v.check_in?.detail.backup).length;
  const agency = household.people.find((p) => p.role === "agency")?.name ?? visits[0]?.expectation.agency ?? "Agency";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">{agency} · Coordinator</p>
          <h1 className="mt-0.5 text-3xl font-semibold tracking-tight">Visit verification</h1>
          <p className="mt-1 text-ink-2">{fmtDateLong(state.now, tz)} · Electronic Visit Verification from the client&apos;s own Ring doorbell</p>
        </div>
        <button
          type="button"
          onClick={onExport}
          className="inline-flex items-center gap-2 rounded-2xl bg-brand px-5 py-3 text-base font-semibold text-white shadow-sm transition hover:bg-brand-strong active:scale-[0.98]"
        >
          <IconDownload size={20} /> Export EVV CSV
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Scheduled visits" value={visits.length} />
        <Stat
          label="Verified at the door"
          value={verified}
          tone={verified ? "ok" : undefined}
          note={simulated ? `${simulated} simulated (demo), not counted` : "Signed code seen by the camera"}
        />
        <Stat label="Exceptions to review" value={exceptions} tone={exceptions ? "warn" : undefined} />
        <Stat label="Backup aides sent" value={backups} />
      </div>

      <Card aria-labelledby="evv-table-title" className="overflow-hidden">
        <CardHeader id="evv-table-title" eyebrow="21st Century Cures Act · EVV" title="Visits" />

        {/* desktop table */}
        <div className="mt-4 hidden overflow-x-auto lg:block">
          <table className="w-full text-left text-[0.95rem]">
            <thead className="border-y border-line bg-canvas/60 text-sm text-ink-3">
              <tr>
                <Th>Visit</Th>
                <Th evv>Service</Th>
                <Th evv>Client · Location</Th>
                <Th evv>Caregiver</Th>
                <Th evv>Date · Time in / out</Th>
                <Th>On site</Th>
                <Th>Verified by</Th>
                <Th>Status · EVV</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visits.map((v, i) => {
                const e = v.expectation;
                const s = statuses[i];
                const f = evvFields(v);
                const provider = (v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver;
                return (
                  <tr key={e.id} className="align-top">
                    <td className="px-3 py-4">
                      <p className="whitespace-nowrap font-mono text-[0.8rem] font-semibold">{e.visit_id ?? e.id}</p>
                      <p className="text-sm text-ink-3">{e.title}</p>
                    </td>
                    <td className="px-3 py-4">
                      <span className="whitespace-nowrap">Personal care</span>
                      <p className="text-sm text-ink-3">T1019</p>
                    </td>
                    <td className="px-3 py-4">
                      <p className="font-semibold">{household.patient.name}</p>
                      <p className="max-w-[11rem] text-sm text-ink-3">{household.patient.address}</p>
                    </td>
                    <td className="px-3 py-4">
                      {provider}
                      {Boolean(v.check_in?.detail.backup) && <p className="text-sm text-ink-3">backup for {e.caregiver}</p>}
                    </td>
                    <td className="px-3 py-4 tabular">
                      <p className="text-sm text-ink-3">{dateIn(e.window_start, tz)}</p>
                      <p className="whitespace-nowrap">
                        {v.check_in ? fmtTime(v.check_in.at, tz) : "—"} → {v.check_out ? fmtTime(v.check_out.at, tz) : v.check_in ? "on site" : "—"}
                      </p>
                      <p className="whitespace-nowrap text-sm text-ink-3">
                        plan {fmtTime(e.window_start, tz)}–{fmtTime(e.window_end, tz)}
                      </p>
                    </td>
                    <td className="px-3 py-4">
                      <Duration v={v} />
                    </td>
                    <td className="px-3 py-4">
                      <VerifiedBy v={v} />
                    </td>
                    <td className="space-y-1.5 px-3 py-4">
                      <StatusChip status={s.key} label={s.label} />
                      <EvvDots fields={f} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* mobile / tablet cards */}
        <ul className="mt-4 divide-y divide-line border-t border-line lg:hidden">
          {visits.map((v, i) => {
            const e = v.expectation;
            const s = statuses[i];
            const provider = (v.check_in?.detail.caregiver as string | undefined) ?? e.caregiver;
            return (
              <li key={e.id} className="space-y-3 px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold">{e.title}</p>
                    <p className="font-mono text-sm text-ink-3">{e.visit_id}</p>
                  </div>
                  <StatusChip status={s.key} label={s.label} />
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[0.95rem]">
                  <dt className="text-ink-3">Service</dt>
                  <dd>Personal care (T1019)</dd>
                  <dt className="text-ink-3">Client</dt>
                  <dd>{household.patient.name}</dd>
                  <dt className="text-ink-3">Location</dt>
                  <dd>{household.patient.address}</dd>
                  <dt className="text-ink-3">Caregiver</dt>
                  <dd>
                    {provider}
                    {Boolean(v.check_in?.detail.backup) && " (backup)"}
                  </dd>
                  <dt className="text-ink-3">Time in/out</dt>
                  <dd className="tabular">
                    {v.check_in ? fmtTime(v.check_in.at, tz) : "—"} → {v.check_out ? fmtTime(v.check_out.at, tz) : v.check_in ? "on site" : "—"}
                  </dd>
                  <dt className="text-ink-3">On site</dt>
                  <dd>
                    <Duration v={v} />
                  </dd>
                </dl>
                <div className="flex flex-wrap items-center gap-3">
                  <VerifiedBy v={v} />
                  <EvvDots fields={evvFields(v)} />
                </div>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card className="p-5 sm:p-6">
        <div className="flex items-start gap-3">
          <IconShield size={26} className="mt-0.5 shrink-0 text-brand" />
          <div>
            <h2 className="text-lg font-semibold">The six EVV data elements</h2>
            <p className="mt-1 text-ink-2">
              Required for Medicaid personal care by the 21st Century Cures Act (§12006). DoorLedger captures them at the door: the aide shows a rotating
              signed code to the client&apos;s Ring doorbell on arrival and departure, so there is no GPS app to spoof and nothing for the client to do.
            </p>
            <ol className="mt-3 grid gap-x-6 gap-y-1.5 text-ink-2 sm:grid-cols-2">
              {EVV_FIELDS.map((f, i) => (
                <li key={f} className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand-strong">{i + 1}</span>
                  {f}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </Card>
    </div>
  );
}

/** "Verified by" cell: only a signed code in a camera frame earns the check mark. */
function VerifiedBy({ v }: { v: VisitState }) {
  if (!v.check_in) return <span className="text-ink-3">—</span>;
  const proof = visitSimulated(v)
    ? "simulated"
    : visitVerified(v)
      ? "verified"
      : isDoorVerified(v.check_in) && !v.check_out
        ? "checked_in"
        : "unverified";
  if (proof === "simulated") {
    return (
      <div className="space-y-1">
        <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-dashed border-warn/30 bg-warn-soft px-2 py-0.5 text-[0.78rem] font-semibold leading-5 text-warn">
          <IconFlask size={13} /> Simulated (demo)
        </span>
        <p className="whitespace-nowrap text-sm text-ink-3" title="No camera footage of a signed code: not counted as verified">Not verified</p>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <SourceBadge source={v.check_in.source} />
      {proof === "verified" || proof === "checked_in" ? (
        <p className="flex items-center gap-1 whitespace-nowrap text-sm font-semibold text-ok">
          <IconCheck size={14} /> {proof === "verified" ? "Verified at the door" : "Check-in verified"}
        </p>
      ) : (
        <p className="flex items-center gap-1 whitespace-nowrap text-sm text-warn">
          <IconX size={14} /> No signed code seen
        </p>
      )}
    </div>
  );
}

function Th({ children, evv }: { children: React.ReactNode; evv?: boolean }) {
  return (
    <th scope="col" className="whitespace-nowrap px-3 py-3 font-semibold">
      {children}
      {evv && <span className="ml-1.5 rounded bg-brand-soft px-1 py-px text-[0.65rem] font-bold text-brand-strong">EVV</span>}
    </th>
  );
}

function Duration({ v }: { v: VisitState }) {
  const planned = v.expectation.planned_minutes ?? 60;
  if (v.minutes_on_site === null) return <span className="text-ink-3">—</span>;
  const pct = Math.min(1, v.minutes_on_site / planned);
  const short = pct < 0.75 && v.check_out;
  return (
    <div className="w-24">
      <p className="tabular">
        <span className="font-semibold">{v.minutes_on_site}</span> <span className="text-ink-3">/ {planned} min</span>
      </p>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
        <div className={cx("h-full rounded-full", short ? "bg-warn-bar" : "bg-ok-bar")} style={{ width: `${pct * 100}%` }} />
      </div>
    </div>
  );
}

function EvvDots({ fields }: { fields: boolean[] }) {
  const n = fields.filter(Boolean).length;
  const complete = n === fields.length;
  return (
    <div className="flex items-center gap-2" title={EVV_FIELDS.map((f, i) => `${fields[i] ? "✓" : "✗"} ${f}`).join("\n")}>
      <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-sm font-semibold", complete ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn")}>
        {complete ? <IconCheck size={14} /> : <IconX size={14} />}
        {n}/6
      </span>
      <span className="sr-only">{complete ? "EVV record complete" : "EVV record incomplete"}</span>
    </div>
  );
}

function Stat({ label, value, tone, note }: { label: string; value: number; tone?: "ok" | "warn"; note?: string }) {
  return (
    <Card as="div" className="px-5 py-4">
      <p className="text-sm font-semibold text-ink-3">{label}</p>
      <p className={cx("mt-1 text-4xl font-bold tabular", tone === "ok" && "text-ok", tone === "warn" && "text-warn")}>{value}</p>
      {note && <p className="mt-0.5 text-sm text-ink-3">{note}</p>}
    </Card>
  );
}
