"use client";
/**
 * The offline capture queue, shared by every host screen.
 *
 * A recording is written to IndexedDB first and uploaded afterwards, so a host can record on the
 * plateau without connectivity, close the tab, and have the flow continue when the browser is back
 * online. Uploads are retried on the `online` event and on a timer; each attempt sends
 * `offline_captured` and the original `captured_at` alongside the file, exactly as the contract
 * describes.
 *
 * Retrying is **bounded**, and that is not a detail:
 *
 * * an attempt that fails waits {@link backoffMs} before the next one (10 s, 20 s, 40 s … capped at
 *   five minutes) instead of hammering the API every 20 s;
 * * after {@link MAX_ATTEMPTS} attempts the recording is given up on (`rejected`) and the panel
 *   offers to delete it or to try once more;
 * * an answer that will never change — 415, 413, 400/422, 403/404 — is final immediately;
 * * **409 means the listing was already confirmed**: the recording is dropped from the queue as
 *   `obsolete` and never sent again, because the API refuses it precisely so that a late upload
 *   cannot push a finished session back to `transcribed` (see docs/onboarding.md);
 * * a row left in `uploading` by a reload is returned to `queued` on mount, not stranded.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getToken } from "@/lib/api";
import type { Translate } from "@/lib/i18n";
import { useT } from "@/lib/i18n";
import { uploadAudio } from "./hostApi";
import * as store from "./offlineStore";
import type { QueuedRecording, UploadResult } from "./types";
import { describeError, newId } from "./utils";

/** How often the queue looks for work while the browser is online. */
const RETRY_INTERVAL_MS = 20000;
/** After this many failed attempts the recording is given up on and the panel says so. */
export const MAX_ATTEMPTS = 6;
/** Backoff after attempt n: 10 s, 20 s, 40 s, 80 s, … capped. Without it a poisoned recording was
 *  re-uploaded every 20 s for as long as the page stayed open. */
const BACKOFF_BASE_MS = 10000;
const BACKOFF_MAX_MS = 5 * 60 * 1000;

/**
 * Answers that will never become a success, however often the file is sent again: an unsupported
 * container (415), a recording over the size limit (413), a body the API rejects (400/422), and a
 * session that is gone or belongs to somebody else (404/403).
 */
const PERMANENT_STATUSES = [400, 403, 404, 413, 415, 422];
/** The API refuses a recording for a session whose listing is already confirmed or published. */
const OBSOLETE_STATUS = 409;
/** Not the recording's fault and not counted as an attempt — the host has to sign in again. */
const UNAUTHORISED_STATUS = 401;

export function backoffMs(attempts: number): number {
  return Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempts - 1));
}

function statusOf(e: unknown): number | null {
  return e instanceof ApiError ? e.status : null;
}

/** What one failed attempt means for the row: try again later, or stop and explain. */
export function classifyFailure(
  e: unknown,
  attempts: number,
  t: Translate,
): { state: "failed" | "rejected" | "obsolete"; message: string } {
  const status = statusOf(e);
  if (status === OBSOLETE_STATUS) return { state: "obsolete", message: t("host.queue.reason.obsolete") };
  if (status !== null && PERMANENT_STATUSES.includes(status)) {
    return { state: "rejected", message: t("host.queue.reason.rejected", { message: describeError(e, t) }) };
  }
  if (attempts >= MAX_ATTEMPTS) {
    return {
      state: "rejected",
      message: t("host.queue.reason.gaveUp", { count: attempts, message: describeError(e, t) }),
    };
  }
  return { state: "failed", message: describeError(e, t) };
}

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
  /** Still owed an upload: queued, in flight, or failed and waiting for its backoff. */
  pending: QueuedRecording[];
  /** Given up on (`rejected`) or refused because the listing is already confirmed (`obsolete`). */
  blocked: QueuedRecording[];
  online: boolean;
  busy: boolean;
  error: string | null;
  enqueue: (input: EnqueueInput) => Promise<QueuedRecording | null>;
  remove: (id: string) => Promise<void>;
  /** Put one given-up recording back in the queue at the host's request. */
  retry: (id: string) => Promise<void>;
  retryAll: () => Promise<void>;
  /** Everything still owed an upload for one onboarding session (the wizard blocks confirm on it). */
  pendingFor: (sessionId: string | null) => QueuedRecording[];
  subscribe: (fn: (result: UploadResult) => void) => () => void;
}

const noop = async () => undefined;

const QueueContext = createContext<QueueValue>({
  ready: false,
  supported: false,
  items: [],
  pending: [],
  blocked: [],
  online: true,
  busy: false,
  error: null,
  enqueue: async () => null,
  remove: noop,
  retry: noop,
  retryAll: noop,
  pendingFor: () => [],
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

  /**
   * Upload every recording that is due, once.
   *
   * A failure is either temporary — the row goes back to `failed` with an exponential backoff and a
   * bounded number of attempts — or final: the API said it will never take this file (`rejected`),
   * or the listing was confirmed while the recording waited (`obsolete`, HTTP 409). A final row
   * leaves the queue and the panel explains it, because retrying it forever is what pushed a
   * completed session back to `transcribed` and corrupted the timing log.
   */
  const flush = useCallback(async () => {
    if (flushing.current || typeof navigator === "undefined" || !navigator.onLine) return;
    if (!getToken()) return; // signed out: uploading would only spend attempts on 401s
    flushing.current = true;
    setBusy(true);
    try {
      const rows = await store.listRecordings();
      for (const row of rows) {
        if (!store.isPending(row) || uploading.current.has(row.id)) continue;
        if (!store.isDue(row)) continue; // still serving its backoff
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
          });
          const next = await store.patchRecording(row.id, {
            state: "uploaded",
            attempts: row.attempts + 1,
            uploaded_at: new Date().toISOString(),
            finished_at: new Date().toISOString(),
            next_attempt_at: undefined,
            transcript: typeof response.transcript === "string" ? response.transcript : undefined,
            job_id: response.job_id ?? null,
            last_error: "",
          });
          setError(null);
          if (next) notify({ record: next, response });
        } catch (e) {
          if (statusOf(e) === UNAUTHORISED_STATUS) {
            // Not this recording's fault: wait for the host to sign in again, spend no attempt.
            await store.patchRecording(row.id, {
              state: "queued",
              next_attempt_at: new Date(Date.now() + backoffMs(1)).toISOString(),
              last_error: t("host.queue.reason.signedOut"),
            });
            setError(t("host.queue.reason.signedOut"));
          } else {
            const attempts = row.attempts + 1;
            const outcome = classifyFailure(e, attempts, t);
            await store.patchRecording(row.id, {
              state: outcome.state,
              attempts,
              // The upload was deferred, whatever the reason — but only a row that will be tried
              // again is still an offline capture on its way to the API.
              captured_offline: outcome.state === "failed" ? true : row.captured_offline,
              last_error: outcome.message,
              next_attempt_at:
                outcome.state === "failed" ? new Date(Date.now() + backoffMs(attempts)).toISOString() : undefined,
              finished_at: outcome.state === "failed" ? undefined : new Date().toISOString(),
            });
            setError(outcome.message);
          }
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
        await store.pruneFinished();
        // A row left in `uploading` by a reload (or a crash) has nobody finishing it: this page
        // instance has started none, so anything it finds in that state is stale and goes back to
        // `queued`. Without this the recording was stranded and the panel claimed the queue was empty.
        await store.reclaimStale(uploading.current);
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

  /** The host asks for one given-up recording to be tried again: a fresh attempt budget. */
  const retry = useCallback(
    async (id: string) => {
      setError(null);
      try {
        await store.patchRecording(id, {
          state: "queued",
          attempts: 0,
          next_attempt_at: undefined,
          finished_at: undefined,
          last_error: "",
        });
      } catch (e) {
        setError(describeError(e, t));
      }
      await refresh();
      void flush();
    },
    [flush, refresh, t],
  );

  /** "Try uploading now": clears every backoff so the host does not wait for the timer. */
  const retryAll = useCallback(async () => {
    setError(null);
    try {
      for (const row of await store.listRecordings()) {
        if (store.isPending(row) && row.next_attempt_at) {
          await store.patchRecording(row.id, { next_attempt_at: undefined });
        }
      }
    } catch {
      /* the flush below still tries whatever is due */
    }
    await flush();
    await refresh();
  }, [flush, refresh]);

  const subscribe = useCallback((fn: (r: UploadResult) => void) => {
    subscribers.current.add(fn);
    return () => {
      subscribers.current.delete(fn);
    };
  }, []);

  const pending = useMemo(() => items.filter(store.isPending), [items]);
  const blocked = useMemo(() => items.filter(store.isBlocked), [items]);
  const pendingFor = useCallback(
    (sessionId: string | null) => (sessionId ? pending.filter((r) => r.session_id === sessionId) : []),
    [pending],
  );

  const value = useMemo<QueueValue>(
    () => ({
      ready,
      supported,
      items,
      pending,
      blocked,
      online,
      busy,
      error,
      enqueue,
      remove,
      retry,
      retryAll,
      pendingFor,
      subscribe,
    }),
    [
      ready,
      supported,
      items,
      pending,
      blocked,
      online,
      busy,
      error,
      enqueue,
      remove,
      retry,
      retryAll,
      pendingFor,
      subscribe,
    ],
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
