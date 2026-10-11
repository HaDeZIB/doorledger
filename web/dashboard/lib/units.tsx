"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { cToF } from "./thermal";

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

export function useUnits() {
  const { unit, setUnit } = useContext(Ctx);
  const fmt = useCallback(
    (c: number, digits = 0) => (unit === "F" ? `${cToF(c).toFixed(digits)}°F` : `${c.toFixed(digits === 0 ? 0 : digits)}°C`),
    [unit],
  );
  const alt = useCallback(
    (c: number, digits = 0) => (unit === "F" ? `${c.toFixed(digits)}°C` : `${cToF(c).toFixed(digits)}°F`),
    [unit],
  );
  return { unit, setUnit, fmt, alt };
}
