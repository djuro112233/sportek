/**
 * Offline capture store.
 *
 * Every recording the host makes is written to IndexedDB **before** any upload is attempted, with
 * its onboarding session id, language, recorded-at timestamp, duration and upload state. That is
 * what makes recording on the plateau (no connectivity) work: the queue survives a page reload,
 * the host can delete an entry, and the upload is retried when the browser comes back online.
 *
 * Audio blobs never leave the device until they are uploaded to this prototype's own API.
 */
import type { QueuedRecording, QueuedState } from "./types";

const DB_NAME = "vrmac-lh-host";
const DB_VERSION = 1;
const STORE = "recordings";

export function indexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (!indexedDbAvailable()) return Promise.reject(new Error("IndexedDB is not available in this browser"));
  if (dbPromise) return dbPromise;
  dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("by_session", "session_id", { unique: false });
        store.createIndex("by_state", "state", { unique: false });
      }
    };
    req.onsuccess = () => {
      const db = req.result;
      db.onclose = () => {
        dbPromise = null;
      };
      resolve(db);
    };
    req.onerror = () => reject(req.error ?? new Error("IndexedDB could not be opened"));
    req.onblocked = () => reject(new Error("IndexedDB is blocked by another tab"));
  }).catch((e) => {
    dbPromise = null;
    throw e;
  });
  return dbPromise;
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        const req = run(transaction.objectStore(STORE));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"));
        transaction.onabort = () => reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
      }),
  );
}

/** Everything in the queue, oldest recording first. */
export async function listRecordings(): Promise<QueuedRecording[]> {
  const rows = await tx<QueuedRecording[]>("readonly", (s) => s.getAll() as IDBRequest<QueuedRecording[]>);
  return rows
    .filter((r) => r && typeof r.id === "string" && r.blob instanceof Blob)
    .sort((a, b) => a.captured_at.localeCompare(b.captured_at));
}

export function getRecording(id: string): Promise<QueuedRecording | undefined> {
  return tx<QueuedRecording | undefined>("readonly", (s) => s.get(id) as IDBRequest<QueuedRecording | undefined>);
}

export async function putRecording(rec: QueuedRecording): Promise<QueuedRecording> {
  await tx("readwrite", (s) => s.put(rec));
  return rec;
}

export async function patchRecording(
  id: string,
  patch: Partial<Omit<QueuedRecording, "id">>,
): Promise<QueuedRecording | undefined> {
  const current = await getRecording(id);
  if (!current) return undefined;
  const next: QueuedRecording = { ...current, ...patch };
  await putRecording(next);
  return next;
}

export function deleteRecording(id: string): Promise<void> {
  return tx<undefined>("readwrite", (s) => s.delete(id) as IDBRequest<undefined>).then(() => undefined);
}

/** Uploaded entries older than `maxAgeMs` are dropped so the device does not fill up with audio. */
export async function pruneUploaded(maxAgeMs = 24 * 60 * 60 * 1000): Promise<number> {
  const now = Date.now();
  const rows = await listRecordings();
  let removed = 0;
  for (const r of rows) {
    if (r.state !== "uploaded" || !r.uploaded_at) continue;
    const at = Date.parse(r.uploaded_at);
    if (Number.isFinite(at) && now - at > maxAgeMs) {
      await deleteRecording(r.id);
      removed += 1;
    }
  }
  return removed;
}

export const PENDING_STATES: QueuedState[] = ["queued", "failed"];

export function isPending(r: QueuedRecording): boolean {
  return r.state === "queued" || r.state === "failed";
}
