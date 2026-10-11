import type { ObservationSource, Severity } from "@/lib/types";
import { SOURCE_LABEL, type VisitStatusKey } from "@/lib/derive";
import { IconAlert, IconBolt, IconCamera, IconCheck, IconFilm, IconFlask, IconInfo } from "./icons";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  as: As = "section",
  ...rest
}: { children: React.ReactNode; className?: string; as?: "section" | "div" | "article" } & React.HTMLAttributes<HTMLElement>) {
  return (
    <As
      className={cx(
        "rounded-3xl border border-line bg-surface shadow-[0_1px_2px_rgba(23,33,43,0.04),0_8px_24px_-12px_rgba(23,33,43,0.08)]",
        className,
      )}
      {...rest}
    >
      {children}
    </As>
  );
}

export function CardHeader({
  title,
  eyebrow,
  right,
  id,
}: {
  title: React.ReactNode;
  eyebrow?: React.ReactNode;
  right?: React.ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5 sm:px-6 sm:pt-6">
      <div className="min-w-0">
        {eyebrow && <p className="text-sm font-semibold uppercase tracking-[0.08em] text-ink-3">{eyebrow}</p>}
        <h2 id={id} className="mt-0.5 text-xl font-semibold tracking-tight text-ink sm:text-[1.35rem]">
          {title}
        </h2>
      </div>
      {right}
    </div>
  );
}

const SOURCE_STYLE: Record<ObservationSource, string> = {
  ring_live_view: "bg-brand-soft text-brand-strong border-brand/25",
  ring_snapshot: "bg-info-soft text-info border-info/25",
  ring_webhook: "bg-[#efeaf8] text-[#4f3a8a] border-[#4f3a8a]/20",
  own_footage: "bg-[#efeee9] text-ink-2 border-line-strong",
  simulated: "bg-warn-soft text-warn border-warn/30 border-dashed",
};

const SOURCE_ICON: Record<ObservationSource, React.ComponentType<{ size?: number }>> = {
  ring_live_view: IconCamera,
  ring_snapshot: IconCamera,
  ring_webhook: IconBolt,
  own_footage: IconFilm,
  simulated: IconFlask,
};

/** Provenance badge — every observation shows where it came from. */
export function SourceBadge({ source, className }: { source: ObservationSource; className?: string }) {
  const Icon = SOURCE_ICON[source];
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[0.78rem] font-semibold leading-5",
        SOURCE_STYLE[source],
        className,
      )}
      title={`Source: ${SOURCE_LABEL[source]}`}
    >
      <Icon size={13} />
      {SOURCE_LABEL[source]}
    </span>
  );
}

export const SEVERITY_STYLE: Record<Severity, { chip: string; bar: string; icon: React.ComponentType<{ size?: number }>; label: string }> = {
  info: { chip: "bg-info-soft text-info", bar: "bg-info", icon: IconInfo, label: "Info" },
  warning: { chip: "bg-warn-soft text-warn", bar: "bg-warn-bar", icon: IconAlert, label: "Needs attention" },
  critical: { chip: "bg-crit-soft text-crit", bar: "bg-crit-bar", icon: IconAlert, label: "Urgent" },
};

export function SeverityChip({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity];
  const Icon = s.icon;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.78rem] font-semibold", s.chip)}>
      <Icon size={13} />
      {s.label}
    </span>
  );
}

export const VISIT_STATUS_STYLE: Record<VisitStatusKey, { chip: string; bar: string; dot: string }> = {
  scheduled: { chip: "bg-[#efeee9] text-ink-2", bar: "bg-ink-3", dot: "bg-ink-3" },
  awaiting: { chip: "bg-info-soft text-info", bar: "bg-info", dot: "bg-info" },
  late: { chip: "bg-warn-soft text-warn", bar: "bg-warn-bar", dot: "bg-warn-bar" },
  in_progress: { chip: "bg-brand-soft text-brand-strong", bar: "bg-brand", dot: "bg-brand" },
  completed: { chip: "bg-ok-soft text-ok", bar: "bg-ok-bar", dot: "bg-ok-bar" },
  short: { chip: "bg-warn-soft text-warn", bar: "bg-warn-bar", dot: "bg-warn-bar" },
  missed: { chip: "bg-crit-soft text-crit", bar: "bg-crit-bar", dot: "bg-crit-bar" },
};

export function StatusChip({ status, label, className }: { status: VisitStatusKey; label: string; className?: string }) {
  const s = VISIT_STATUS_STYLE[status];
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-sm font-semibold", s.chip, className)}>
      {status === "completed" ? <IconCheck size={14} /> : <span className={cx("h-2 w-2 rounded-full", s.dot)} />}
      {label}
    </span>
  );
}

export function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-sm font-semibold", className)}>
      {children}
    </span>
  );
}

export function ProgressRing({
  value,
  size = 132,
  stroke = 12,
  color = "var(--color-brand)",
  children,
  label,
}: {
  value: number;
  size?: number;
  stroke?: number;
  color?: string;
  children?: React.ReactNode;
  label: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--color-line)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v)}
          style={{ transition: "stroke-dashoffset 600ms ease, stroke 400ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-2xl border border-dashed border-line-strong px-4 py-6 text-center text-ink-3">{children}</p>;
}
