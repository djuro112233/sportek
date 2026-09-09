"use client";
/**
 * The **active authoring time** clock of the onboarding wizard.
 *
 * It counts a second only while all three are true: the wizard is open, the tab is visible
 * (Page Visibility API) and the host interacted within the last minute. Waiting for the validator,
 * a phone call in the middle of the flow or a backgrounded tab therefore never inflate the number
 * the ≤ 30 minute target refers to. Roughly every 30 counted seconds the delta is sent to
 * `POST /api/onboarding/sessions/{id}/heartbeat`; a failed heartbeat keeps its delta and retries.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { heartbeat } from "./hostApi";

const IDLE_AFTER_MS = 60000;
const HEARTBEAT_AFTER_SECONDS = 30;
const INTERACTIONS = ["pointerdown", "keydown", "input", "change", "wheel", "touchstart", "focusin"] as const;

export type TimerState = "counting" | "paused_hidden" | "paused_idle" | "stopped";

export interface ActiveTimer {
  /** Seconds counted in this browser (what the mm:ss display shows). */
  activeSeconds: number;
  /** The accumulated total the API last confirmed, or null before the first heartbeat. */
  serverSeconds: number | null;
  state: TimerState;
  /** Send whatever has not been reported yet (called on unmount and before confirming). */
  flush: () => Promise<void>;
}

export function useActiveTimer(sessionId: string | null, enabled: boolean): ActiveTimer {
  const [activeSeconds, setActiveSeconds] = useState(0);
  const [serverSeconds, setServerSeconds] = useState<number | null>(null);
  const [state, setState] = useState<TimerState>("stopped");
  const pending = useRef(0);
  const lastInteraction = useRef(Date.now());
  const sending = useRef(false);
  const sessionRef = useRef<string | null>(sessionId);
  sessionRef.current = sessionId;

  const send = useCallback(async () => {
    const id = sessionRef.current;
    const delta = Math.round(pending.current);
    if (!id || delta < 1 || sending.current) return;
    sending.current = true;
    pending.current -= delta; // keep any seconds counted while the request is in flight
    try {
      const r = await heartbeat(id, delta);
      if (typeof r?.active_seconds === "number") setServerSeconds(r.active_seconds);
    } catch {
      pending.current += delta; // offline or the API is down: report it with the next heartbeat
    } finally {
      sending.current = false;
    }
  }, []);

  // Any interaction keeps the clock running for another minute.
  useEffect(() => {
    if (!enabled) return;
    const mark = () => {
      lastInteraction.current = Date.now();
    };
    for (const type of INTERACTIONS) document.addEventListener(type, mark, { passive: true });
    const onVisibility = () => {
      if (document.visibilityState === "visible") mark();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      for (const type of INTERACTIONS) document.removeEventListener(type, mark);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setState("stopped");
      return;
    }
    lastInteraction.current = Date.now();
    const id = window.setInterval(() => {
      const hidden = typeof document !== "undefined" && document.visibilityState !== "visible";
      const idle = Date.now() - lastInteraction.current > IDLE_AFTER_MS;
      if (hidden) {
        setState("paused_hidden");
        return;
      }
      if (idle) {
        setState("paused_idle");
        return;
      }
      setState("counting");
      pending.current += 1;
      setActiveSeconds((s) => s + 1);
      if (pending.current >= HEARTBEAT_AFTER_SECONDS) void send();
    }, 1000);
    return () => {
      window.clearInterval(id);
      setState("stopped");
      void send();
    };
  }, [enabled, sessionId, send]);

  return { activeSeconds, serverSeconds, state, flush: send };
}
