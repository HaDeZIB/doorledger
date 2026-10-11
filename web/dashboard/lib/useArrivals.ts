"use client";

import { useRef } from "react";

/**
 * Tells which items arrived after the component first rendered, so only genuinely new findings
 * and actions animate in (not everything on page load). Items that disappear (demo reset or a
 * scenario rewinding the clock) are forgotten, so they animate again when they come back.
 */
export function useArrivals(ids: string[]): (id: string) => boolean {
  const base = useRef<Set<string> | null>(null);
  if (base.current === null) base.current = new Set(ids);
  const current = new Set(ids);
  for (const id of base.current) if (!current.has(id)) base.current.delete(id);
  const known = base.current;
  return (id: string) => !known.has(id);
}
