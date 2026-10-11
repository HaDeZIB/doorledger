"use client";

import { useState } from "react";
import type { Observation } from "@/lib/types";
import { fmtTimeSec } from "@/lib/time";
import { SourceBadge, cx } from "./ui";

/**
 * Proof frame for an observation. Live mode loads the JPEG from /api/evidence/{path};
 * mock mode (or a failed load) draws an illustrated doorbell-camera frame instead so the
 * product story is intact without real footage. Illustrations are labelled as such.
 */
export function EvidenceFrame({
  obs,
  url,
  tz,
  className,
  compact = false,
}: {
  obs: Observation;
  url: string | null;
  tz: string;
  className?: string;
  compact?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const showImg = url && !failed;
  return (
    <figure className={cx("overflow-hidden rounded-2xl border border-line bg-[#0f1720]", className)}>
      <div className="relative aspect-[16/10] w-full">
        {showImg ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt={`Doorbell camera frame: ${obs.kind.replaceAll("_", " ")}`}
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setFailed(true)}
          />
        ) : (
          <Scene kind={obs.kind} detail={obs.detail} />
        )}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-6">
          <span className="font-mono text-[0.72rem] font-semibold tracking-wide text-white/95">
            FRONT DOOR · {fmtTimeSec(obs.at, tz)}
          </span>
          {!showImg && <span className="text-[0.68rem] font-medium text-white/80">illustration</span>}
        </div>
      </div>
      {!compact && (
        <figcaption className="flex flex-wrap items-center gap-2 bg-surface px-3 py-2 text-sm text-ink-2">
          <SourceBadge source={obs.source} />
          <span className="tabular">{Math.round(obs.confidence * 100)}% confidence</span>
        </figcaption>
      )}
    </figure>
  );
}

function Scene({ kind, detail }: { kind: Observation["kind"]; detail: Record<string, unknown> }) {
  const showBox = kind === "package_dropped";
  const gone = kind === "package_removed";
  const person = kind === "presence_check_in" || kind === "presence_check_out" || kind === "person_at_door";
  const code = kind === "presence_check_in" || kind === "presence_check_out";
  const car = kind === "vehicle_arrived";
  return (
    <svg viewBox="0 0 320 200" className="absolute inset-0 h-full w-full" role="img" aria-label="Illustrated doorbell camera frame">
      <defs>
        <radialGradient id="vig" cx="50%" cy="45%" r="75%">
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.6" />
        </radialGradient>
        <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#c9d8de" />
          <stop offset="1" stopColor="#e8e2d2" />
        </linearGradient>
        <linearGradient id="floor" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#b9a98d" />
          <stop offset="1" stopColor="#d9c9a6" />
        </linearGradient>
      </defs>
      <rect width="320" height="200" fill="url(#sky)" />
      {/* yard + street */}
      <rect y="70" width="320" height="40" fill="#9fb59a" />
      <rect y="84" width="320" height="10" fill="#8d9296" />
      {car && (
        <g transform="translate(180 70)">
          <rect x="0" y="6" width="70" height="16" rx="5" fill="#f2f2f2" stroke="#6b7280" />
          <rect x="12" y="0" width="40" height="10" rx="3" fill="#cfd8de" stroke="#6b7280" />
          <circle cx="14" cy="23" r="4" fill="#374151" />
          <circle cx="56" cy="23" r="4" fill="#374151" />
          <rect x="-4" y="-6" width="80" height="34" fill="none" stroke="#22d3ee" strokeWidth="1.5" strokeDasharray="4 3" />
          <text x="-2" y="-9" fontSize="8" fill="#0e7490" fontFamily="monospace" fontWeight="700">vehicle</text>
        </g>
      )}
      {/* porch floor in perspective */}
      <path d="M0 200 L40 110 L280 110 L320 200 Z" fill="url(#floor)" />
      <path d="M40 110 L280 110" stroke="#8b7a5c" strokeWidth="2" />
      {/* door frame sides */}
      <rect x="0" y="0" width="34" height="200" fill="#efe9dc" />
      <rect x="286" y="0" width="34" height="200" fill="#efe9dc" />
      {/* mat */}
      <path d="M110 170 L126 132 L204 132 L220 170 Z" fill="#6b5a45" />
      {showBox && (
        <g>
          <path d="M136 150 L142 124 L188 124 L194 150 Z" fill="#f4f4f2" stroke="#4b5563" />
          <path d="M142 124 L150 114 L194 114 L188 124 Z" fill="#e5e7eb" stroke="#4b5563" />
          <path d="M188 124 L194 114 L198 140 L194 150 Z" fill="#d1d5db" stroke="#4b5563" />
          <rect x="152" y="132" width="26" height="8" fill="#2f6fb3" />
          <text x="155" y="138.5" fontSize="5.5" fill="#fff" fontFamily="sans-serif" fontWeight="700">KEEP COLD</text>
          <rect x="128" y="106" width="78" height="52" fill="none" stroke="#facc15" strokeWidth="1.6" strokeDasharray="5 3" />
          <rect x="128" y="96" width="70" height="11" fill="#facc15" />
          <text x="131" y="104" fontSize="7.5" fill="#1f2937" fontFamily="monospace" fontWeight="700">package 94%</text>
          {Boolean(detail.in_sun) && (
            <g>
              <path d="M40 0 L120 0 L230 200 L100 200 Z" fill="#fde68a" opacity="0.28" />
            </g>
          )}
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
          <circle cx="160" cy="62" r="17" fill="#5b6470" />
          <path d="M126 180 Q128 92 160 88 Q192 92 194 180 Z" fill="#5b6470" />
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
      <rect width="320" height="200" fill="url(#vig)" />
    </svg>
  );
}
