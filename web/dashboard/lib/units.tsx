"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { cToF } from "./thermal";

// US families read °F first; °C is always shown alongside as the secondary unit.
export type Unit = "F" | "C";
const KEY = "doorledger.unit";

const Ctx = createContext<{ unit: Unit; setUnit: (u: Unit) => void }>({ unit: "F", setUnit: () => {} });

export function UnitsProvider({ children }: { children: React.ReactNode }) {
  const [unit, setUnitState] = useState<Unit>("F");
  useEffect(() => {
    try {
      const v = localStorage.getItem(KEY);
      if (v === "C" || v === "F") setUnitState(v);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const setUnit = useCallback((u: Unit) => {
    setUnitState(u);
    try {
      localStorage.setItem(KEY, u);
    } catch {
      /* ignore */
    }
  }, []);
  return <Ctx.Provider value={{ unit, setUnit }}>{children}</Ctx.Provider>;
}

/** toFixed without "-0" and with a real minus sign. */
export function num(v: number, digits = 0): string {
  const s = v.toFixed(digits);
  const zero = Number(s) === 0;
  const out = zero ? s.replace(/^-/, "") : s;
  return out.replace(/^-/, "−");
}

export const degF = (c: number, digits = 0) => `${num(cToF(c), digits)}°F`;
export const degC = (c: number, digits = 0) => `${num(c, digits)}°C`;
/** "32°F (0°C)" — used where the unit toggle isn't available (e.g. canned text). */
export const degBoth = (c: number, digits = 0) => `${degF(c, digits)} (${degC(c, digits)})`;

export function useUnits() {
  const { unit, setUnit } = useContext(Ctx);
  /** Primary unit. */
  const fmt = useCallback((c: number, digits = 0) => (unit === "F" ? degF(c, digits) : degC(c, digits)), [unit]);
  /** Secondary unit. */
  const alt = useCallback((c: number, digits = 0) => (unit === "F" ? degC(c, digits) : degF(c, digits)), [unit]);
  /** "32°F (0°C)" in the current primary/secondary order. */
  const both = useCallback((c: number, digits = 0) => `${fmt(c, digits)} (${alt(c, digits)})`, [fmt, alt]);
  return { unit, setUnit, fmt, alt, both };
}
