"use client";
import { useEffect, useState } from "react";

/** Seconds elapsed between `start` and `end` (ms timestamps); ticks every second while `end` is null. */
export function useElapsed(start: number | null, end: number | null): number {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (start === null || end !== null) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [start, end]);

  if (start === null) return 0;
  return Math.max(0, Math.round(((end ?? now) - start) / 1000));
}
