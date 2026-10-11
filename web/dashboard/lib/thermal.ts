// Client-side port of core/src/doorledger/exposure.py, used ONLY by mock mode so the demo
// clock can tick the exposure estimate smoothly. In live mode the backend's estimate wins.
//
//   T(t) = T_amb + (T0 - T_amb) * exp(-t / tau)
//
// The box drifts toward the outside temperature: on a cold porch the danger is FREEZING
// (frozen insulin must be discarded); on a hot porch it is the excursion limit (~30 °C).

import type { ExposureDirection, ExposureEstimate, MedicationProfile } from "./types";

export const DEFAULT_TAU_MIN = 90;
export const SUN_TAU_FACTOR = 0.5;
export const DEFAULT_FREEZE_C = 0;

/** Minutes from drop-off until the box warms up to `threshold` (null = never). */
function timeTo(threshold: number, t0: number, ambient: number, tau: number): number | null {
  if (ambient <= threshold) return null;
  if (t0 >= threshold) return 0;
  return -tau * Math.log((threshold - ambient) / (t0 - ambient));
}

/** Minutes from drop-off until the box cools down to `threshold` (null = never). */
function timeToCold(threshold: number, t0: number, ambient: number, tau: number): number | null {
  if (ambient >= threshold) return null;
  if (t0 <= threshold) return 0;
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
  const freeze = profile.freeze_c ?? DEFAULT_FREEZE_C;
  const elapsed = Math.max(minutesOnPorch, 0);
  const internal = ambientC + (t0 - ambientC) * Math.exp(-elapsed / tau);

  const tExc = timeTo(profile.excursion_max_c, t0, ambientC, tau);
  const untilExc = tExc === null ? null : Math.max(tExc - elapsed, 0);
  const tFreeze = timeToCold(freeze, t0, ambientC, tau);
  const untilFreeze = tFreeze === null ? null : Math.max(tFreeze - elapsed, 0);
  const direction: ExposureDirection = ambientC < profile.store_min_c ? "cold" : ambientC > profile.store_max_c ? "hot" : null;

  const compromised = internal >= profile.excursion_max_c || internal <= freeze;
  const soonest = Math.min(...[untilExc, untilFreeze].filter((x): x is number => x !== null), Infinity);
  const status = compromised ? "compromised" : soonest <= (opts.atRiskWindowMin ?? 20) ? "at_risk" : "safe";
  const until = direction === "cold" ? untilFreeze : untilExc;
  const unsafe = direction === "cold" ? freeze : direction === "hot" ? profile.excursion_max_c : null;
  return {
    minutes_on_porch: Math.round(elapsed * 10) / 10,
    ambient_c: ambientC,
    estimated_internal_c: Math.round(internal * 10) / 10,
    minutes_until_excursion_max: until === null ? null : Math.round(until * 10) / 10,
    status,
    direction,
    unsafe_c: unsafe,
  };
}

export const cToF = (c: number) => (c * 9) / 5 + 32;

/**
 * Direction of the danger for an estimate. Newer backends send `direction`; older ones don't,
 * so fall back to comparing the outside temperature with the storage range.
 */
export function exposureDirection(
  est: Pick<ExposureEstimate, "ambient_c" | "direction"> | null | undefined,
  med: MedicationProfile | null | undefined,
  ambientFallbackC?: number,
): ExposureDirection {
  if (est?.direction !== undefined && est?.direction !== null) return est.direction;
  const amb = est?.ambient_c ?? ambientFallbackC;
  if (amb === undefined || !med) return null;
  return amb < med.store_min_c ? "cold" : amb > med.store_max_c ? "hot" : null;
}

/** The temperature limit the box is heading toward (freezing when cold, excursion when hot). */
export function unsafeLimitC(
  est: Pick<ExposureEstimate, "unsafe_c"> | null | undefined,
  med: MedicationProfile | null | undefined,
  dir: ExposureDirection,
): number | null {
  if (typeof est?.unsafe_c === "number") return est.unsafe_c;
  if (!med) return null;
  if (dir === "cold") return med.freeze_c ?? DEFAULT_FREEZE_C;
  return med.excursion_max_c;
}
