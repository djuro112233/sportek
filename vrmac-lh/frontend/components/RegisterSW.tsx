"use client";
import { useEffect } from "react";

/** Registers the service worker for the host PWA (offline shell). */
export default function RegisterSW() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
