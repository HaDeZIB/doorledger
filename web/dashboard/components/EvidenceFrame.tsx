"use client";

import { useState } from "react";
import type { Observation } from "@/lib/types";
import { fmtTime, fmtTimeSec } from "@/lib/time";
import { OBS_LABEL, visionNote } from "@/lib/derive";
import { IconFlask } from "./icons";
import { SourceBadge, cx } from "./ui";

export interface FrameCandidate {
  obs: Observation;
  url: string | null;
}

/**
 * Proof frame for an observation. Live mode loads the JPEG from /api/evidence/{path}
 * (real Ring frames analysed by the vision model). Pass `alternates` to fall back to another
 * observation's real frame (e.g. the drop frame when the pickup frame is missing); the label,
 * time, source and caption always describe the frame actually shown.
 *
 * Without any loadable image: Ring-sourced observations get a labelled illustration (mock
 * mode), but `simulated` observations NEVER get a picture — they show an honest "no camera
 * frame" panel, because no footage exists for them yet.
 */
export function EvidenceFrame({
  obs,
  url,
  alternates = [],
  tz,
  className,
  compact = false,
  wideOverlay = false,
}: {
  obs: Observation;
  url: string | null;
  alternates?: FrameCandidate[];
  tz: string;
  className?: string;
  compact?: boolean;
  /** On wide screens (xl) drop the caption and overlay the source badge on the frame, to save height. */
  wideOverlay?: boolean;
}) {
  const [failed, setFailed] = useState<Set<string>>(() => new Set());
  const candidates = [{ obs, url }, ...alternates];
  const shown = candidates.find((c) => c.url && !failed.has(c.url));
  // no real frame: illustrate the first non-simulated candidate, if any
  const drawn = shown ? null : candidates.find((c) => c.obs.source !== "simulated") ?? null;
  const o = shown?.obs ?? drawn?.obs ?? obs;
  const none = !shown && !drawn;
  const note = visionNote(o);
  const caption = shown && typeof o.detail.caption === "string" ? o.detail.caption : null;
  const captionShort = caption && typeof o.detail.caption_short === "string" ? o.detail.caption_short : caption;
  // e.g. "Ring doorbell frame at 2:07 PM: package on snowy doorstep"
  const alt = `${o.source === "own_footage" ? "Own footage" : "Ring doorbell"} frame at ${fmtTime(o.at, tz)}: ${note ?? OBS_LABEL[o.kind].toLowerCase()}`;
  return (
    <figure
      className={cx("overflow-hidden rounded-2xl border", none ? "border-dashed border-warn/40 bg-canvas" : "border-line bg-[#0f1720]", className)}
      title={caption ?? undefined}
    >
      <div className="relative aspect-[16/10] w-full">
        {shown?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={shown.url}
            src={shown.url}
            alt={alt}
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setFailed((s) => new Set(s).add(shown.url!))}
          />
        ) : drawn ? (
          <Scene kind={drawn.obs.kind} detail={drawn.obs.detail} label={`Illustration, not a camera frame: ${OBS_LABEL[drawn.obs.kind].toLowerCase()} at ${fmtTime(drawn.obs.at, tz)}`} />
        ) : (
          <NoFrame compact={compact} roomForBadge={wideOverlay && !compact} />
        )}
        {wideOverlay && !compact && (
          <span className="absolute left-2 top-2 hidden xl:block" title={note ? `Vision: ${note}` : undefined}>
            <SourceBadge source={o.source} className="shadow-sm" />
          </span>
        )}
        {!none && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap items-end justify-between gap-x-2 bg-gradient-to-t from-black/85 via-black/55 to-transparent px-2.5 pb-1.5 pt-6">
            <span className="whitespace-nowrap font-mono text-[0.7rem] font-semibold tracking-wide text-white">
              <span className={cx(compact ? "hidden" : "xl:hidden")}>FRONT DOOR · </span>
              {fmtTimeSec(o.at, tz)}
            </span>
            {shown?.url ? (
              o !== obs ? (
                <span className="text-[0.68rem] font-medium text-white">{OBS_SHORT[o.kind] ?? "earlier frame"}</span>
              ) : (
                caption && wideOverlay && !compact && <span className="hidden min-w-0 truncate text-[0.62rem] font-medium text-white xl:block">{captionShort}</span>
              )
            ) : (
              <span className="text-[0.68rem] font-medium text-white">{o !== obs ? `${OBS_SHORT[o.kind] ?? "earlier frame"} · ` : ""}illustration</span>
            )}
          </div>
        )}
      </div>
      {!compact && (
        <figcaption className={cx("bg-surface px-3 py-2 text-sm text-ink-2", wideOverlay && "xl:hidden")}>
          <span className="flex flex-wrap items-center gap-2">
            <SourceBadge source={o.source} />
            {o.source !== "simulated" && <span className="tabular">{Math.round(o.confidence * 100)}% confidence</span>}
            {none && <span className="tabular text-ink-3">{fmtTimeSec(o.at, tz)}</span>}
          </span>
          {caption && <span className="mt-1 block text-[0.8rem] text-ink-3">{caption}</span>}
          {note && (
            <span className="mt-1 block text-ink-2">
              <span className="font-semibold text-ink-3">{o.source === "simulated" ? "Note:" : "Vision:"}</span> {note}
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}

function NoFrame({ compact, roomForBadge = false }: { compact: boolean; roomForBadge?: boolean }) {
  return (
    <div className={cx("hatch absolute inset-0 flex flex-col items-center justify-center gap-1.5 px-4 text-center text-warn", roomForBadge && "xl:pt-7")}>
      <IconFlask size={compact ? 22 : 28} />
      <p className={cx("font-semibold", compact ? "text-sm" : "text-[0.95rem]")}>No camera frame</p>
      <p className={cx("text-ink-3", compact ? "text-[0.72rem] leading-tight" : "text-sm")}>Simulated event · footage not filmed yet</p>
    </div>
  );
}

const OBS_SHORT: Partial<Record<Observation["kind"], string>> = {
  package_dropped: "drop-off frame",
  vehicle_arrived: "arrival frame",
  presence_check_in: "check-in frame",
};

// Illustrated (clearly labelled) stand-in for a Ring frame in mock mode: a snowy Chicago doorstep.
const FLAKES = [
  [22, 18], [58, 40], [96, 12], [132, 34], [170, 20], [212, 44], [250, 16], [292, 30], [44, 62], [118, 66],
  [196, 70], [272, 60], [80, 92], [236, 96], [150, 54], [306, 82],
];

function Scene({ kind, label }: { kind: Observation["kind"]; detail: Record<string, unknown>; label: string }) {
  const showBox = kind === "package_dropped";
  const gone = kind === "package_removed";
  const person = kind === "presence_check_in" || kind === "presence_check_out" || kind === "person_at_door";
  const code = kind === "presence_check_in" || kind === "presence_check_out";
  const car = kind === "vehicle_arrived";
  return (
    <svg viewBox="0 0 320 200" className="absolute inset-0 h-full w-full" role="img" aria-label={label}>
      <defs>
        <radialGradient id="vig" cx="50%" cy="45%" r="75%">
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.55" />
        </radialGradient>
        <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#aebccb" />
          <stop offset="1" stopColor="#d9e1e8" />
        </linearGradient>
        <linearGradient id="floor" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#c9ced3" />
          <stop offset="1" stopColor="#e9edf0" />
        </linearGradient>
      </defs>
      <rect width="320" height="200" fill="url(#sky)" />
      {/* snowy yard + plowed street */}
      <rect y="70" width="320" height="40" fill="#eef2f5" />
      <rect y="84" width="320" height="10" fill="#7d858c" />
      <path d="M0 84 Q40 80 80 84 T160 84 T240 84 T320 84" fill="none" stroke="#f8fafb" strokeWidth="3" />
      {car && (
        <g transform="translate(180 70)">
          <rect x="0" y="6" width="70" height="16" rx="5" fill="#f2f2f2" stroke="#6b7280" />
          <rect x="12" y="0" width="40" height="10" rx="3" fill="#cfd8de" stroke="#6b7280" />
          <rect x="12" y="-1.5" width="40" height="3" rx="1.5" fill="#ffffff" />
          <circle cx="14" cy="23" r="4" fill="#374151" />
          <circle cx="56" cy="23" r="4" fill="#374151" />
          <rect x="-4" y="-6" width="80" height="34" fill="none" stroke="#22d3ee" strokeWidth="1.5" strokeDasharray="4 3" />
          <text x="-2" y="-9" fontSize="8" fill="#0e7490" fontFamily="monospace" fontWeight="700">vehicle</text>
        </g>
      )}
      {/* porch floor in perspective, dusted with snow */}
      <path d="M0 200 L40 110 L280 110 L320 200 Z" fill="url(#floor)" />
      <path d="M40 110 L280 110" stroke="#8d969e" strokeWidth="2" />
      <path d="M0 200 L22 150 Q60 158 70 200 Z M320 200 L298 150 Q262 160 250 200 Z" fill="#ffffff" opacity="0.9" />
      {/* door frame sides */}
      <rect x="0" y="0" width="34" height="200" fill="#e6e1d6" />
      <rect x="286" y="0" width="34" height="200" fill="#e6e1d6" />
      {/* mat */}
      <path d="M110 170 L126 132 L204 132 L220 170 Z" fill="#5d5145" />
      {showBox && (
        <g>
          <path d="M136 150 L142 124 L188 124 L194 150 Z" fill="#c8a173" stroke="#4b5563" />
          <path d="M142 124 L150 114 L194 114 L188 124 Z" fill="#d8b588" stroke="#4b5563" />
          <path d="M150 114 L194 114 L192 117 Q170 112 152 117 Z" fill="#ffffff" />
          <path d="M188 124 L194 114 L198 140 L194 150 Z" fill="#b38b5e" stroke="#4b5563" />
          <rect x="152" y="132" width="26" height="8" fill="#2f6fb3" />
          <text x="154.5" y="138.5" fontSize="5.2" fill="#fff" fontFamily="sans-serif" fontWeight="700">REFRIGERATE</text>
          <rect x="128" y="106" width="78" height="52" fill="none" stroke="#facc15" strokeWidth="1.6" strokeDasharray="5 3" />
          <rect x="128" y="96" width="70" height="11" fill="#facc15" />
          <text x="131" y="104" fontSize="7.5" fill="#1f2937" fontFamily="monospace" fontWeight="700">package 94%</text>
        </g>
      )}
      {gone && (
        <g>
          <path d="M136 150 L142 124 L188 124 L194 150 Z" fill="none" stroke="#f97316" strokeWidth="1.5" strokeDasharray="4 3" />
          <rect x="132" y="100" width="72" height="11" fill="#f97316" />
          <text x="135" y="108" fontSize="7.5" fill="#fff" fontFamily="monospace" fontWeight="700">package gone</text>
        </g>
      )}
      {person && (
        <g>
          <circle cx="160" cy="62" r="17" fill="#3f4752" />
          <path d="M126 180 Q128 92 160 88 Q192 92 194 180 Z" fill="#3f4752" />
          {code && (
            <g>
              <rect x="174" y="96" width="28" height="44" rx="4" fill="#111827" />
              <rect x="177" y="100" width="22" height="22" fill="#fff" />
              {Array.from({ length: 25 }).map((_, i) => {
                const on = [0, 1, 3, 5, 6, 8, 10, 12, 13, 16, 18, 19, 21, 24].includes(i);
                return on ? <rect key={i} x={178 + (i % 5) * 4} y={101 + Math.floor(i / 5) * 4} width="4" height="4" fill="#111827" /> : null;
              })}
              <text x="178" y="132" fontSize="6" fill="#86efac" fontFamily="monospace" fontWeight="700">482 913</text>
              <rect x="170" y="84" width="38" height="62" fill="none" stroke="#4ade80" strokeWidth="1.6" strokeDasharray="5 3" />
              <rect x="170" y="74" width="62" height="11" fill="#4ade80" />
              <text x="173" y="82" fontSize="7.5" fill="#052e16" fontFamily="monospace" fontWeight="700">code ✓ valid</text>
            </g>
          )}
        </g>
      )}
      {/* falling snow */}
      <g fill="#ffffff" opacity="0.85">
        {FLAKES.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.6 : 1.1} />
        ))}
      </g>
      <rect width="320" height="200" fill="url(#vig)" />
    </svg>
  );
}
