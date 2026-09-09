"use client";
/**
 * The voice-first onboarding wizard.
 *
 * Record (or type) → transcript → the assistant drafts **title and description only** → the host
 * enters and confirms price, season, capacity, accessibility and location → consent v1 → the
 * listing goes into the validation queue as a draft.
 *
 * Two clocks are kept apart on purpose: the **active authoring time** (mm:ss, only while this tab
 * is visible and the host is working, reported through heartbeats) is the one the target refers to;
 * the elapsed wall-clock time is shown next to it and labelled as including any waiting.
 *
 * The wizard state is mirrored in localStorage and every recording in IndexedDB, so a reload — or a
 * day without connectivity — resumes exactly where the host stopped.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getMeta } from "@/lib/api";
import { useLang, useT } from "@/lib/i18n";
import ConsentText from "./ConsentText";
import styles from "./host.module.css";
import {
  confirmListing,
  createSession,
  generateDraft,
  getSession,
  getVillages,
  pollForTranscript,
  saveTranscript,
} from "./hostApi";
import { ListingDetailsFields, NarrativeFields } from "./ListingDetails";
import ListingPreview, { StatusBadge } from "./ListingPreview";
import { useOfflineQueue } from "./offlineQueue";
import OfflineQueuePanel from "./OfflineQueuePanel";
import type {
  Confirmations,
  ConfirmResponse,
  HostUser,
  ListingFormValues,
  ListingPayload,
  StructuredField,
  Village,
} from "./types";
import { useActiveTimer } from "./useActiveTimer";
import { useElapsed } from "./useElapsed";
import { useRecorder } from "./useRecorder";
import {
  describeError,
  EMPTY_FORM,
  formToFields,
  missingGroups,
  mmss,
  narrativeFromDraft,
  NO_CONFIRMATIONS,
  unconfirmed,
  validateForm,
} from "./utils";

const STEPS = [1, 2, 3, 4, 5, 6, 7] as const;
type Step = (typeof STEPS)[number];

const STORAGE_KEY = "vrmac.host.wizard.v1";
const DEFAULT_TARGET_MINUTES = 30;

interface Persisted {
  sessionId: string;
  step: Step;
  language: "cnr" | "en";
  villageId: string;
  onBehalfOf: string;
  transcript: string;
  form: ListingFormValues;
  confirmed: Confirmations;
  extractionMethod: string;
  translationPending: boolean;
  startedAt: string;
}

function loadPersisted(): Persisted | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<Persisted>;
    if (!p || typeof p.sessionId !== "string" || !p.sessionId) return null;
    return {
      sessionId: p.sessionId,
      step: (STEPS as readonly number[]).includes(p.step ?? 0) ? (p.step as Step) : 2,
      language: p.language === "en" ? "en" : "cnr",
      villageId: typeof p.villageId === "string" ? p.villageId : "",
      onBehalfOf: typeof p.onBehalfOf === "string" ? p.onBehalfOf : "",
      transcript: typeof p.transcript === "string" ? p.transcript : "",
      form: { ...EMPTY_FORM, ...(p.form ?? {}) },
      confirmed: { ...NO_CONFIRMATIONS, ...(p.confirmed ?? {}) },
      extractionMethod: typeof p.extractionMethod === "string" ? p.extractionMethod : "",
      translationPending: Boolean(p.translationPending),
      startedAt: typeof p.startedAt === "string" ? p.startedAt : new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export default function Wizard({ user }: { user: HostUser }) {
  const t = useT();
  const { lang } = useLang();
  const queue = useOfflineQueue();
  const recorder = useRecorder();

  const [step, setStep] = useState<Step>(1);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [language, setLanguage] = useState<"cnr" | "en">("cnr");
  const [villageId, setVillageId] = useState("");
  const [onBehalfOf, setOnBehalfOf] = useState("");
  const [villages, setVillages] = useState<Village[]>([]);
  const [transcript, setTranscript] = useState("");
  const [typed, setTyped] = useState("");
  const [form, setForm] = useState<ListingFormValues>(EMPTY_FORM);
  const [confirmed, setConfirmed] = useState<Confirmations>(NO_CONFIRMATIONS);
  const [extractionMethod, setExtractionMethod] = useState("");
  const [translationPending, setTranslationPending] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [result, setResult] = useState<ConfirmResponse | null>(null);
  const [targetMinutes, setTargetMinutes] = useState(DEFAULT_TARGET_MINUTES);
  const [startedAt, setStartedAt] = useState<string>("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [resumed, setResumed] = useState(false);
  const [confirmedAtMs, setConfirmedAtMs] = useState<number | null>(null);
  const [restored, setRestored] = useState(false);

  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const firstRender = useRef(true);
  const handledRecordings = useRef<Set<string>>(new Set());

  const timer = useActiveTimer(sessionId, step < 7 && !result);
  const startedMs = startedAt ? Date.parse(startedAt) : null;
  const elapsedSeconds = useElapsed(startedMs !== null && Number.isFinite(startedMs) ? startedMs : null, confirmedAtMs);

  // --- meta, villages, restore ---------------------------------------------------------------

  useEffect(() => {
    getMeta()
      .then((m) => {
        if (typeof m.onboarding_target_minutes === "number" && m.onboarding_target_minutes > 0) {
          setTargetMinutes(m.onboarding_target_minutes);
        }
      })
      .catch(() => undefined);
    getVillages()
      .then(setVillages)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const p = loadPersisted();
    setRestored(true);
    if (!p) return;
    setSessionId(p.sessionId);
    setStep(p.step);
    setLanguage(p.language);
    setVillageId(p.villageId);
    setOnBehalfOf(p.onBehalfOf);
    setTranscript(p.transcript);
    setForm(p.form);
    setConfirmed(p.confirmed);
    setExtractionMethod(p.extractionMethod);
    setTranslationPending(p.translationPending);
    setStartedAt(p.startedAt);
    setResumed(true);
    // Refresh from the API when possible; being offline must not throw the draft away.
    getSession(p.sessionId)
      .then((s) => {
        if (s.transcript && !p.transcript) setTranscript(s.transcript);
        if (s.started_at) setStartedAt(s.started_at);
      })
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
          discardPersisted();
          setSessionId(null);
          setStep(1);
          setResumed(false);
        }
      });
  }, []);

  // Mirror the wizard state so a reload (or a closed tab on the plateau) resumes it.
  useEffect(() => {
    if (!restored || !sessionId || result) return;
    const p: Persisted = {
      sessionId,
      step,
      language,
      villageId,
      onBehalfOf,
      transcript,
      form,
      confirmed,
      extractionMethod,
      translationPending,
      startedAt: startedAt || new Date().toISOString(),
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    } catch {
      /* private mode: the queue in IndexedDB is what really matters */
    }
  }, [
    restored,
    sessionId,
    result,
    step,
    language,
    villageId,
    onBehalfOf,
    transcript,
    form,
    confirmed,
    extractionMethod,
    translationPending,
    startedAt,
  ]);

  // Move focus to the step heading whenever the step changes.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  // --- offline queue → transcript ------------------------------------------------------------

  useEffect(() => {
    if (!sessionId || step > 3) return;
    const done = queue.items.find(
      (r) => r.session_id === sessionId && r.state === "uploaded" && !handledRecordings.current.has(r.id),
    );
    if (!done) return;
    handledRecordings.current.add(done.id);
    if (done.transcript && done.transcript.trim()) {
      setTranscript(done.transcript);
      setStatus(t("host.record.transcriptReady"));
      setStep(3);
    } else {
      setStatus(t("host.record.queuedForTranscription"));
      setPolling(true);
    }
  }, [queue.items, sessionId, step, t]);

  useEffect(() => {
    if (!polling || !sessionId) return;
    const ctrl = new AbortController();
    pollForTranscript(sessionId, {
      signal: ctrl.signal,
      onTick: (n) => setStatus(t("host.record.polling", { n })),
    })
      .then((s) => {
        setPolling(false);
        if (s.transcript && s.transcript.trim()) {
          setTranscript(s.transcript);
          setStatus(t("host.record.transcriptReady"));
          setStep(3);
        } else {
          setStatus(t("host.record.pollTimeout"));
        }
      })
      .catch((e) => {
        setPolling(false);
        if (!(e instanceof DOMException)) setError(describeError(e, t));
      });
    return () => ctrl.abort();
  }, [polling, sessionId, t]);

  // --- actions -------------------------------------------------------------------------------

  const patchForm = useCallback((patch: Partial<ListingFormValues>) => setForm((f) => ({ ...f, ...patch })), []);
  const setConfirmation = useCallback(
    (field: StructuredField, value: boolean) => setConfirmed((c) => ({ ...c, [field]: value })),
    [],
  );

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const village = villages.find((v) => v.id === villageId) ?? null;
      const session = await createSession({
        language,
        village: village?.slug,
        host_user_id: user.role === "ambassador" && onBehalfOf.trim() ? onBehalfOf.trim() : undefined,
      });
      handledRecordings.current = new Set();
      setSessionId(session.id);
      setStartedAt(session.started_at || new Date().toISOString());
      setForm({ ...EMPTY_FORM, village_id: villageId });
      setConfirmed(NO_CONFIRMATIONS);
      setTranscript("");
      setStatus(t("host.start.created"));
      setStep(2);
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  }

  async function keepRecording() {
    if (!sessionId || !recorder.recording) return;
    const rec = recorder.recording;
    const queued = await queue.enqueue({
      session_id: sessionId,
      language,
      blob: rec.blob,
      duration_s: rec.durationSeconds,
      captured_at: rec.capturedAt,
    });
    recorder.reset();
    setStatus(
      queued && !navigator.onLine
        ? t("host.record.savedOffline", { count: queue.pending.length + 1 })
        : t("host.record.uploading"),
    );
  }

  async function saveTyped() {
    if (!sessionId || !typed.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const session = await saveTranscript(sessionId, typed.trim());
      setTranscript(session.transcript ?? typed.trim());
      setStatus(t("host.record.typedSaved"));
      setStep(3);
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  }

  async function persistTranscript(): Promise<boolean> {
    if (!sessionId) return false;
    try {
      await saveTranscript(sessionId, transcript.trim());
      setStatus(t("host.transcript.saved"));
      return true;
    } catch (e) {
      setError(describeError(e, t));
      return false;
    }
  }

  async function generate() {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const ok = await persistTranscript();
      if (!ok) return;
      const draft = await generateDraft(sessionId);
      const narrative = narrativeFromDraft(draft);
      setForm((f) => ({ ...f, ...narrative }));
      setExtractionMethod(draft.extraction_method ?? "");
      setTranslationPending(Boolean(draft.translation_pending));
      setStatus(t("host.draft.ready"));
      setStep(4);
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!sessionId) return;
    const invalid = validateForm(form, t);
    if (invalid) {
      setError(invalid);
      setStep(5);
      return;
    }
    if (unconfirmed(confirmed).length > 0) {
      setError(t("host.confirm.blocked"));
      setStep(5);
      return;
    }
    if (!consentChecked) {
      setError(t("host.consent.required"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await timer.flush();
      const listing: ListingPayload = { ...formToFields(form, confirmed) };
      if (form.village_id) listing.village_id = form.village_id;
      const r = await confirmListing(sessionId, listing);
      setResult(r);
      setConfirmedAtMs(Date.now());
      discardPersisted();
      setStatus(t("host.done.status"));
      setStep(7);
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  }

  function startAnother() {
    discardPersisted();
    handledRecordings.current = new Set();
    setResult(null);
    setConfirmedAtMs(null);
    setSessionId(null);
    setTranscript("");
    setTyped("");
    setForm(EMPTY_FORM);
    setConfirmed(NO_CONFIRMATIONS);
    setExtractionMethod("");
    setTranslationPending(false);
    setConsentChecked(false);
    setStartedAt("");
    setStatus("");
    setError(null);
    setResumed(false);
    setStep(1);
  }

  // --- render --------------------------------------------------------------------------------

  const targetSeconds = targetMinutes * 60;
  const activeSeconds = Math.max(timer.activeSeconds, timer.serverSeconds ?? 0);
  const overTarget = activeSeconds > targetSeconds;
  const villageOfForm = villages.find((v) => v.id === form.village_id) ?? null;
  const missing = useMemo(() => missingGroups(form), [form]);
  const pendingConfirmations = unconfirmed(confirmed);

  return (
    <section aria-labelledby="wizard-heading">
      <h2 id="wizard-heading">{t("host.wizard.heading")}</h2>
      <p>{t("host.wizard.intro")}</p>

      <ol className={styles.stepper}>
        {STEPS.map((s) => (
          <li key={s} className={s === step ? styles.current : s < step ? styles.done : undefined}>
            <span className="visually-hidden">{s < step ? t("host.step.done") : s === step ? t("host.step.current") : ""}</span>
            {s}. {t(`host.step.${s}`)}
          </li>
        ))}
      </ol>

      {step < 7 ? (
        <div className={styles.timerBar}>
          <div>
            <div className={`${styles.timer} ${overTarget ? styles.overTarget : ""}`}>
              <span className="visually-hidden">{t("host.timer.activeLabel")} </span>
              {mmss(activeSeconds)}
            </div>
            <div className="small">{t(`host.timer.state.${timer.state}`)}</div>
          </div>
          <div className={styles.timerMeta}>
            <span>{t("host.timer.target", { minutes: targetMinutes })}</span>
            <span>{t("host.timer.elapsed", { time: mmss(elapsedSeconds) })}</span>
            <span>{t("host.timer.note")}</span>
          </div>
        </div>
      ) : null}

      <p role="status" aria-live="polite" className="small">
        {status}
      </p>
      {error ? (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      ) : null}
      {resumed && step < 7 ? (
        <p className="alert alert-ok small" role="note">
          {t("host.wizard.resumed")}
        </p>
      ) : null}

      {/* ---------------------------------------------------------------- step 1: start */}
      {step === 1 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.1")}
          </h3>
          <fieldset className={styles.group}>
            <legend>{t("host.start.language")}</legend>
            <p className={styles.hint}>{t("host.start.languageHint")}</p>
            <div className={styles.radioRow}>
              {(["cnr", "en"] as const).map((l) => (
                <label key={l} className={styles.check} htmlFor={`start-lang-${l}`}>
                  <input
                    id={`start-lang-${l}`}
                    type="radio"
                    name="start-language"
                    checked={language === l}
                    onChange={() => setLanguage(l)}
                  />
                  <span>{t(`host.lang.${l}`)}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className={styles.group}>
            <legend>{t("host.start.village")}</legend>
            <label className="field" htmlFor="start-village">
              <span>{t("host.field.village")}</span>
              <select
                id="start-village"
                value={villageId}
                onChange={(e) => {
                  setVillageId(e.target.value);
                  patchForm({ village_id: e.target.value });
                }}
                aria-describedby="start-village-hint"
              >
                <option value="">{t("host.field.choose")}</option>
                {Array.from(new Set(villages.map((v) => v.municipality))).map((m) => (
                  <optgroup key={m} label={m}>
                    {villages
                      .filter((v) => v.municipality === m)
                      .map((v) => (
                        <option key={v.id} value={v.id}>
                          {`${lang === "cnr" ? v.name_local : v.name_en}${v.facts_verified ? "" : ` (${t("host.village.unverified")})`}`}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <p className={styles.hint} id="start-village-hint">
              {t("host.start.villageHint")}
            </p>
            {villages.length === 0 ? <p className="small muted">{t("host.start.villagesUnavailable")}</p> : null}
          </fieldset>

          {user.role === "ambassador" && (
            <fieldset className={styles.group}>
              <legend>{t("host.start.onBehalf")}</legend>
              <label className="field" htmlFor="start-behalf">
                <span>{t("host.start.onBehalfField")}</span>
                <input
                  id="start-behalf"
                  value={onBehalfOf}
                  onChange={(e) => setOnBehalfOf(e.target.value)}
                  aria-describedby="start-behalf-hint"
                  autoComplete="off"
                />
              </label>
              <p className={styles.hint} id="start-behalf-hint">
                {t("host.start.onBehalfHint")}
              </p>
            </fieldset>
          )}

          <div className={styles.actions}>
            <button type="button" className="btn btn-primary" onClick={() => void start()} disabled={busy || !villageId}>
              {busy ? t("common.loading") : t("host.start.begin")}
            </button>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------- step 2: record */}
      {step === 2 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.2")}
          </h3>
          <p>{t("host.record.intro")}</p>
          <p className={styles.hint}>{t("host.record.prompt")}</p>

          {recorder.state === "unsupported" ? (
            <p className="alert alert-warn" role="note">
              {t("host.record.unsupported")}
            </p>
          ) : null}
          {recorder.state === "denied" ? (
            <p className="alert alert-warn" role="note">
              {t("host.record.denied")}
            </p>
          ) : null}
          {recorder.state === "error" ? (
            <p className="alert alert-danger" role="alert">
              {t("host.record.error", { message: recorder.errorMessage })}
            </p>
          ) : null}

          <div className={styles.recordControls}>
            {recorder.state === "recording" ? (
              <>
                <button type="button" className={`btn btn-primary ${styles.bigButton}`} onClick={recorder.stop}>
                  {t("host.record.stop")}
                </button>
                <span className={`${styles.duration} ${styles.recDot}`} role="timer" aria-live="off">
                  {mmss(recorder.seconds)}
                </span>
                <span className="visually-hidden" role="status" aria-live="polite">
                  {t("host.record.recording")}
                </span>
              </>
            ) : (
              <button
                type="button"
                className={`btn btn-primary ${styles.bigButton}`}
                onClick={() => void recorder.start()}
                disabled={recorder.state === "unsupported" || recorder.state === "requesting"}
              >
                {recorder.recording ? t("host.record.again") : t("host.record.start")}
              </button>
            )}
          </div>

          {recorder.recording ? (
            <div>
              <p>{t("host.record.playback")}</p>
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <audio src={recorder.recording.url} controls aria-label={t("host.record.playback")} />
              <div className={styles.actions}>
                <button type="button" className="btn btn-primary" onClick={() => void keepRecording()}>
                  {t("host.record.keep")}
                </button>
                <button type="button" className="btn btn-secondary" onClick={recorder.reset}>
                  {t("host.record.discard")}
                </button>
              </div>
            </div>
          ) : null}

          <fieldset className={styles.group}>
            <legend>{t("host.record.alternatives")}</legend>
            <label className="field" htmlFor="record-file">
              <span>{t("host.record.upload")}</span>
              <input
                id="record-file"
                type="file"
                accept="audio/*"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) recorder.adopt(file);
                  e.target.value = "";
                }}
              />
            </label>
            <label className="field" htmlFor="record-typed">
              <span>{t("host.record.typeInstead")}</span>
              <textarea
                id="record-typed"
                rows={5}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                aria-describedby="record-typed-hint"
              />
            </label>
            <p className={styles.hint} id="record-typed-hint">
              {t("host.record.typeHint")}
            </p>
            <button type="button" className="btn btn-secondary" onClick={() => void saveTyped()} disabled={busy || !typed.trim()}>
              {t("host.record.typeSave")}
            </button>
          </fieldset>

          <OfflineQueuePanel sessionId={sessionId} />

          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>
              {t("common.back")}
            </button>
            {transcript ? (
              <button type="button" className="btn btn-primary" onClick={() => setStep(3)}>
                {t("common.next")}
              </button>
            ) : null}
          </div>
        </div>
      )}

      {/* ----------------------------------------------------------- step 3: transcript */}
      {step === 3 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.3")}
          </h3>
          <p>{t("host.transcript.intro")}</p>
          <label className="field" htmlFor="transcript">
            <span>{t("host.transcript.label")}</span>
            <textarea id="transcript" rows={10} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
          </label>
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={() => setStep(2)}>
              {t("common.back")}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => void persistTranscript()} disabled={busy}>
              {t("host.transcript.save")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void generate()}
              disabled={busy || !transcript.trim()}
            >
              {busy ? t("host.transcript.generating") : t("host.transcript.generate")}
            </button>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------- step 4: draft */}
      {step === 4 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.4")}
          </h3>
          <p>{t("host.draft.intro")}</p>
          <NarrativeFields
            values={form}
            onChange={patchForm}
            idPrefix="wiz"
            extractionMethod={extractionMethod || undefined}
            translationPending={translationPending}
          />
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={() => setStep(3)}>
              {t("common.back")}
            </button>
            <button type="button" className="btn btn-primary" onClick={() => setStep(5)}>
              {t("common.next")}
            </button>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------------- step 5: details */}
      {step === 5 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.5")}
          </h3>
          <p>{t("host.details.intro")}</p>
          <ListingDetailsFields
            values={form}
            onChange={patchForm}
            confirmed={confirmed}
            onConfirm={setConfirmation}
            villages={villages}
            idPrefix="wiz"
          />
          {missing.length > 0 ? (
            <p className="alert alert-warn small" role="note">
              {t("host.details.stillEmpty", { fields: missing.map((f) => t(`host.missing.${f}`)).join(", ") })}
            </p>
          ) : null}
          {pendingConfirmations.length > 0 ? (
            <p className="alert alert-warn" role="note">
              {t("host.confirm.pending", {
                fields: pendingConfirmations.map((f) => t(`host.missing.${f}`)).join(", "),
              })}
            </p>
          ) : null}
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={() => setStep(4)}>
              {t("common.back")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                const invalid = validateForm(form, t);
                if (invalid) {
                  setError(invalid);
                  return;
                }
                if (pendingConfirmations.length > 0) {
                  setError(t("host.confirm.blocked"));
                  return;
                }
                setError(null);
                setStep(6);
              }}
            >
              {t("common.next")}
            </button>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------------- step 6: consent */}
      {step === 6 && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.6")}
          </h3>
          <p>{t("host.consent.intro")}</p>
          <ConsentText />
          <label className={styles.check} htmlFor="consent-check">
            <input
              id="consent-check"
              type="checkbox"
              checked={consentChecked}
              onChange={(e) => setConsentChecked(e.target.checked)}
            />
            <span>{t("host.consent.checkbox")}</span>
          </label>
          <p className={styles.hint}>{t("host.consent.withdraw")}</p>
          <div className={styles.actions}>
            <button type="button" className="btn btn-secondary" onClick={() => setStep(5)}>
              {t("common.back")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void submit()}
              disabled={busy || !consentChecked}
            >
              {busy ? t("host.consent.submitting") : t("host.consent.submit")}
            </button>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ step 7: done */}
      {step === 7 && result && (
        <div className="card">
          <h3 tabIndex={-1} ref={headingRef}>
            {t("host.step.7")}
          </h3>
          <p className="alert alert-ok" role="status">
            {t("host.done.queued")} <StatusBadge status={result.listing.status} />
          </p>
          <dl className={styles.facts}>
            <dt>{t("host.done.active")}</dt>
            <dd>
              {mmss(result.active_seconds)} — {t("host.done.target", { minutes: result.target_minutes })} —{" "}
              <strong>{result.within_active_target ? t("host.done.withinTarget") : t("host.done.overTarget")}</strong>
            </dd>
            <dt>{t("host.done.elapsed")}</dt>
            <dd>
              {mmss(result.elapsed_to_confirm_seconds)} — {t("host.done.elapsedNote")}
            </dd>
            <dt>{t("host.done.consentRecord")}</dt>
            <dd>{result.consent_record_id}</dd>
          </dl>
          <h4>{t("host.done.preview")}</h4>
          <ListingPreview listing={result.listing} villages={villages} />
          <div className={styles.actions}>
            <Link className="btn btn-primary" href="/host/listings">
              {t("host.done.toListings")}
            </Link>
            <button type="button" className="btn btn-secondary" onClick={startAnother}>
              {t("host.done.another")}
            </button>
          </div>
        </div>
      )}

      {step === 7 && !result ? <p className="alert alert-warn">{t("host.done.missingResult")}</p> : null}

      {villageOfForm && !villageOfForm.facts_verified && step >= 5 && step < 7 ? (
        <p className="small muted">{t("host.village.unverifiedShort")}</p>
      ) : null}
    </section>
  );
}

function discardPersisted() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
