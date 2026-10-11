// Client-side port of core/src/doorledger/exposure.py, used ONLY by mock mode so the demo
// clock can tick the exposure estimate smoothly. In live mode the backend's estimate wins.
//
//   T(t) = T_amb + (T0 - T_amb) * exp(-t / tau)

import type { ExposureEstimate, MedicationProfile } from "./types";

export const DEFAULT_TAU_MIN = 90;
export const SUN_TAU_FACTOR = 0.5;

function timeTo(threshold: number, t0: number, ambient: number, tau: number): number | null {
  if (ambient <= threshold) return null;
  if (t0 >= threshold) return 0;
  return -tau * Math.log((threshold - ambient) / (t0 - ambient));
}

export function estimate(
  minutesOnPorch: number,
  ambientC: number,
  profile: MedicationProfile,
  opts: { initialC?: number; inSun?: boolean; tauMin?: number; atRiskWindowMin?: number } = {},
): ExposureEstimate {
  const t0 = opts.initialC ?? 5;
  const tau = (opts.tauMin ?? DEFAULT_TAU_MIN) * (opts.inSun ? SUN_TAU_FACTOR : 1);
  const elapsed = Math.max(minutesOnPorch, 0);
  const internal = ambientC + (t0 - ambientC) * Math.exp(-elapsed / tau);
  const tExc = timeTo(profile.excursion_max_c, t0, ambientC, tau);
  const untilExc = tExc === null ? null : Math.max(tExc - elapsed, 0);
  const compromised = internal >= profile.excursion_max_c;
  const status = compromised
    ? "compromised"
    : untilExc !== null && untilExc <= (opts.atRiskWindowMin ?? 20)
      ? "at_risk"
      : "safe";
  return {
    minutes_on_porch: Math.round(elapsed * 10) / 10,
    ambient_c: ambientC,
    estimated_internal_c: Math.round(internal * 10) / 10,
    minutes_until_excursion_max: untilExc === null ? null : Math.round(untilExc * 10) / 10,
    status,
  };
}

export const cToF = (c: number) => (c * 9) / 5 + 32;
