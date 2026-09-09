"use client";
/**
 * The offline capture queue, shared by every host screen.
 *
 * A recording is written to IndexedDB first and uploaded afterwards, so a host can record on the
 * plateau without connectivity, close the tab, and have the flow continue when the browser is back
 * online. Uploads are retried on the `online` event and on a timer; each attempt sends
 * `offline_captured` and the original `captured_at` alongside the file, exactly as the contract
 * describes.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useT } from "@/lib/i18n";
import { uploadAudio } from "./hostApi";
import * as store from "./offlineStore";
import type { QueuedRecording, UploadResult } from "./types";
import { describeError, newId } from "./utils";

const RETRY_INTERVAL_MS = 20000;

export interface EnqueueInput {
  session_id: string;
  language: string;
  blob: Blob;
  duration_s: number;
  /** Defaults to "now"; a recording restored from disk keeps the moment it was recorded. */
  captured_at?: string;
}

export interface QueueValue {
  /** False until the queue has been read back from IndexedDB (the restore-on-mount step). */
  ready: boolean;
  supported: boolean;
  items: QueuedRecording[];
  pending: QueuedRecording[];
  online: boolean;
  busy: boolean;
  error: string | null;
  enqueue: (input: EnqueueInput) => Promise<QueuedRecording | null>;
  remove: (id: string) => Promise<void>;
  retryAll: () => Promise<void>;
  subscribe: (fn: (result: UploadResult) => void) => () => void;
}

const noop = async () => undefined;

const QueueContext = createContext<QueueValue>({
  ready: false,
  supported: false,
  items: [],
  pending: [],
  online: true,
  busy: false,
  error: null,
  enqueue: async () => null,
  remove: noop,
  retryAll: noop,
  subscribe: () => () => undefined,
});

export function extForMime(mime: string): string {
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("mpeg")) return "mp3";
  if (mime.includes("wav")) return "wav";
  return "webm";
}

export function OfflineQueueProvider({ children }: { children: React.ReactNode }) {
  const t = useT();
  const [items, setItems] = useState<QueuedRecording[]>([]);
  const [ready, setReady] = useState(false);
  const [supported, setSupported] = useState(true);
  const [online, setOnline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uploading = useRef<Set<string>>(new Set());
  const subscribers = useRef<Set<(r: UploadResult) => void>>(new Set());
  const flushing = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await store.listRecordings());
    } catch {
      /* the queue simply stays as it is */
    }
  }, []);

  const notify = useCallback((result: UploadResult) => {
    for (const fn of Array.from(subscribers.current)) fn(result);
  }, []);

  /** Upload every pending recording once; keeps failures in the queue for the next attempt. */
  const flush = useCallback(async () => {
    if (flushing.current || typeof navigator === "undefined" || !navigator.onLine) return;
    flushing.current = true;
    setBusy(true);
    try {
      const rows = await store.listRecordings();
      for (const row of rows) {
        if (!store.isPending(row) || uploading.current.has(row.id)) continue;
        uploading.current.add(row.id);
        await store.patchRecording(row.id, { state: "uploading" });
        await refresh();
        try {
          const response = await uploadAudio(row.session_id, {
            blob: row.blob,
            filename: `recording-${row.id}.${extForMime(row.mime)}`,
            capturedAt: row.captured_at,
            // A recording captured without connectivity, or one whose first attempt failed, is an
            // offline capture as far as the timing log is concerned.
            offlineCaptured: row.captured_offline || row.attempts > 0,
            durationSeconds: row.duration_s,
          });
          const next = await store.patchRecording(row.id, {
            state: "uploaded",
            attempts: row.attempts + 1,
            uploaded_at: new Date().toISOString(),
            transcript: typeof response.transcript === "string" ? response.transcript : undefined,
            job_id: response.job_id ?? null,
            last_error: "",
          });
          setError(null);
          if (next) notify({ record: next, response });
        } catch (e) {
          await store.patchRecording(row.id, {
            state: "failed",
            attempts: row.attempts + 1,
            captured_offline: true, // the upload was deferred, whatever the reason
            last_error: describeError(e, t),
          });
          setError(describeError(e, t));
        } finally {
          uploading.current.delete(row.id);
          await refresh();
        }
      }
    } finally {
      flushing.current = false;
      setBusy(false);
    }
  }, [notify, refresh, t]);

  // Restore the queue from IndexedDB on mount — a reload never loses a recording.
  useEffect(() => {
    let cancelled = false;
    if (!store.indexedDbAvailable()) {
      setSupported(false);
      setReady(true);
      return;
    }
    setOnline(navigator.onLine);
    (async () => {
      try {
        await store.pruneUploaded();
        const rows = await store.listRecordings();
        if (cancelled) return;
        setItems(rows);
      } catch (e) {
        if (!cancelled) {
          setSupported(false);
          setError(describeError(e, t));
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `t` changes with the language; the restore must run once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Retry when connectivity returns, and on a timer while anything is pending.
  useEffect(() => {
    if (!ready || !supported) return;
    const goOnline = () => {
      setOnline(true);
      void flush();
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    const id = window.setInterval(() => {
      if (navigator.onLine) void flush();
    }, RETRY_INTERVAL_MS);
    void flush();
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      window.clearInterval(id);
    };
  }, [ready, supported, flush]);

  const enqueue = useCallback(
    async (input: EnqueueInput): Promise<QueuedRecording | null> => {
      const offline = typeof navigator !== "undefined" && !navigator.onLine;
      const record: QueuedRecording = {
        id: newId(),
        session_id: input.session_id,
        language: input.language,
        captured_at: input.captured_at ?? new Date().toISOString(),
        duration_s: Math.max(0, Math.round(input.duration_s)),
        mime: input.blob.type || "audio/webm",
        size: input.blob.size,
        blob: input.blob,
        state: "queued",
        attempts: 0,
        captured_offline: offline,
      };
      try {
        await store.putRecording(record);
      } catch (e) {
        setSupported(false);
        setError(describeError(e, t));
        return null;
      }
      await refresh();
      void flush();
      return record;
    },
    [flush, refresh, t],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await store.deleteRecording(id);
      } catch (e) {
        setError(describeError(e, t));
      }
      await refresh();
    },
    [refresh, t],
  );

  const retryAll = useCallback(async () => {
    setError(null);
    await flush();
  }, [flush]);

  const subscribe = useCallback((fn: (r: UploadResult) => void) => {
    subscribers.current.add(fn);
    return () => {
      subscribers.current.delete(fn);
    };
  }, []);

  const pending = useMemo(() => items.filter(store.isPending), [items]);

  const value = useMemo<QueueValue>(
    () => ({ ready, supported, items, pending, online, busy, error, enqueue, remove, retryAll, subscribe }),
    [ready, supported, items, pending, online, busy, error, enqueue, remove, retryAll, subscribe],
  );

  return <QueueContext.Provider value={value}>{children}</QueueContext.Provider>;
}

export function useOfflineQueue(): QueueValue {
  return useContext(QueueContext);
}

/** Run `fn` whenever a queued recording of `sessionId` finishes uploading. */
export function useUploadResults(sessionId: string | null, fn: (result: UploadResult) => void): void {
  const { subscribe } = useOfflineQueue();
  const handler = useRef(fn);
  handler.current = fn;
  useEffect(() => {
    if (!sessionId) return;
    return subscribe((result) => {
      if (result.record.session_id === sessionId) handler.current(result);
    });
  }, [sessionId, subscribe]);
}
