// Time helpers. All display formatting is done in the household's timezone so that the
// server render and the client render agree (no hydration mismatch) and so that a family
// member in Chicago sees Rosa's local time, which is what the care plan is written in.

export const DEFAULT_TZ = "America/New_York";

/** "GMT-04:00" style offset for a timezone at a given instant → "-04:00". */
export function tzOffset(tz: string, at: Date): string {
  const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "longOffset" })
    .formatToParts(at)
    .find((p) => p.type === "timeZoneName")?.value;
  if (!part || part === "GMT") return "+00:00";
  return part.replace("GMT", "");
}

/** Today's calendar date (YYYY-MM-DD) in a timezone. */
export function todayIn(tz: string, now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Build an ISO timestamp for a wall-clock time on a date in a timezone. */
export function zonedISO(date: string, hhmm: string, tz: string): string {
  const [h, m] = hhmm.split(":");
  const sec = hhmm.split(":")[2] ?? "00";
  const noon = new Date(`${date}T12:00:00Z`);
  return `${date}T${h.padStart(2, "0")}:${m.padStart(2, "0")}:${sec.padStart(2, "0")}${tzOffset(tz, noon)}`;
}

export function ms(iso: string): number {
  return new Date(iso).getTime();
}

export function minutesBetween(a: string, b: string): number {
  return (ms(b) - ms(a)) / 60000;
}

export function fmtTime(iso: string, tz: string = DEFAULT_TZ): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function fmtTimeSec(iso: string, tz: string = DEFAULT_TZ): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

export function fmtHourShort(iso: string, tz: string = DEFAULT_TZ): string {
  const s = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric" }).format(new Date(iso));
  return s.replace(" AM", "a").replace(" PM", "p");
}

export function fmtDateLong(iso: string, tz: string = DEFAULT_TZ): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date(iso));
}

export function dateIn(iso: string, tz: string = DEFAULT_TZ): string {
  return todayIn(tz, new Date(iso));
}

/** Minutes past local midnight for an instant, in a timezone. */
export function minuteOfDay(iso: string, tz: string = DEFAULT_TZ): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  return get("hour") * 60 + get("minute") + get("second") / 60;
}

/** 83.4 → "1 h 23 min", 12 → "12 min". */
export function fmtDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

/** Clock-style h:mm:ss / mm:ss for the exposure clock. */
export function fmtClock(minutes: number): string {
  const total = Math.max(0, Math.floor(minutes * 60));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function relative(fromIso: string, nowIso: string): string {
  const d = minutesBetween(fromIso, nowIso);
  if (d < 1) return "just now";
  if (d < 60) return `${Math.round(d)} min ago`;
  return `${fmtDuration(d)} ago`;
}
