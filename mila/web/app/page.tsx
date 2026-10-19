'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import AnswerView from '@/components/AnswerView';
import CitationSheet from '@/components/CitationSheet';
import ConsentDialog from '@/components/ConsentDialog';
import EmergencyCard from '@/components/EmergencyCard';
import Footer, { type DeleteResult } from '@/components/Footer';
import MicButton, { type MicState } from '@/components/MicButton';
import TranscriptConfirm from '@/components/TranscriptConfirm';
import { ask, deleteSession, errorMessageKey, getSession, isApiError, postPreferences, resolveAudioUrl, speak, transcribe } from '@/lib/api';
import { DEFAULT_LOCALE, detectLocale, htmlLang, translator, type MsgKey } from '@/lib/i18n';
import { clearAll, loadPrefs, loadSession, prefsLocale, saveSession, savePrefs } from '@/lib/storage';
import type { AskResponse, Citation, InputMode, Locale, StoredSession } from '@/lib/types';
import { isRecordingSupported, Player, Recorder, RecorderError, type PlayerState } from '@/lib/voice';

type Stage =
  | { kind: 'boot' }
  | { kind: 'consent' }
  | { kind: 'ready' }
  | { kind: 'recording' }
  | { kind: 'transcribing' }
  | { kind: 'confirm'; text: string }
  | { kind: 'asking'; text: string; mode: InputMode };

interface Result {
  response: AskResponse;
  question: string;
}

interface UiError {
  key: MsgKey;
  retry: (() => void) | null;
}

/** Text that "Listen" reads aloud when the server did not attach audio. */
function speakableText(response: AskResponse): string {
  if (response.outcome === 'answered') {
    return response.sentences.map((s) => s.text.trim()).filter(Boolean).join(' ');
  }
  return [response.message, response.referral?.message ?? ''].map((s) => s.trim()).filter(Boolean).join(' ');
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export default function Page() {
  const [stage, setStage] = useState<Stage>({ kind: 'boot' });
  const [locale, setLocale] = useState<Locale>(DEFAULT_LOCALE);
  const [lowBandwidth, setLowBandwidth] = useState(false);
  const [session, setSession] = useState<StoredSession | null>(null);
  const [micSupported, setMicSupported] = useState<boolean | null>(null);
  const [micNote, setMicNote] = useState<MsgKey | null>(null);
  const [draft, setDraft] = useState('');
  const [seconds, setSeconds] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [playerState, setPlayerState] = useState<PlayerState>('idle');
  const [audioBusy, setAudioBusy] = useState(false);

  const recorderRef = useRef<Recorder | null>(null);
  const playerRef = useRef<Player | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLElement>(null);

  const t = useMemo(() => translator(locale), [locale]);

  const player = useCallback((): Player => {
    if (!playerRef.current) playerRef.current = new Player();
    return playerRef.current;
  }, []);

  const recorder = useCallback((): Recorder => {
    if (!recorderRef.current) recorderRef.current = new Recorder();
    return recorderRef.current;
  }, []);

  // --- boot: read storage, detect language, validate the stored session -----------------------
  useEffect(() => {
    const prefs = loadPrefs();
    setLowBandwidth(prefs.low_bandwidth);
    setMicSupported(isRecordingSupported());
    const stored = loadSession();
    if (stored) {
      setSession(stored);
      setLocale({ lang: stored.lang, script: stored.script });
      setStage({ kind: 'ready' });
      const controller = new AbortController();
      getSession(stored.session_id, controller.signal).catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (isApiError(err) && err.kind === 'http' && err.status === 403) {
          clearAll();
          setSession(null);
          setStage({ kind: 'consent' });
          setError({ key: 'session_expired', retry: null });
        }
        // Network trouble or a missing route: keep the stored session; a later request surfaces the error.
      });
      return () => controller.abort();
    }
    setLocale(prefsLocale(prefs) ?? detectLocale(typeof navigator !== 'undefined' ? navigator.languages : undefined));
    setStage({ kind: 'consent' });
    return undefined;
  }, []);

  useEffect(() => {
    document.documentElement.lang = htmlLang(locale);
  }, [locale]);

  useEffect(() => player().subscribe(setPlayerState), [player]);

  useEffect(
    () => () => {
      recorderRef.current?.cancel();
      playerRef.current?.stop();
    },
    [],
  );

  // recording timer
  useEffect(() => {
    if (stage.kind !== 'recording') {
      setSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500);
    return () => clearInterval(id);
  }, [stage.kind]);

  // bring a new result into view
  useEffect(() => {
    if (result && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    }
  }, [result]);

  // --- preferences --------------------------------------------------------------------------
  const handleLocaleChange = useCallback(
    (next: Locale) => {
      setLocale(next);
      savePrefs({ lang: next.lang, script: next.script });
      if (session) {
        const updated: StoredSession = { ...session, lang: next.lang, script: next.script };
        saveSession(updated);
        setSession(updated);
        postPreferences(session.session_id, { lang: next.lang, script: next.script, region: session.region }).catch(
          () => undefined,
        );
      }
    },
    [session],
  );

  const handleLowBandwidth = useCallback(
    (value: boolean) => {
      setLowBandwidth(value);
      savePrefs({ low_bandwidth: value });
      if (session) {
        postPreferences(session.session_id, { low_bandwidth: value }).catch(() => undefined);
      }
    },
    [session],
  );

  const handleConsentDone = useCallback((s: StoredSession) => {
    saveSession(s);
    setSession(s);
    setError(null);
    setStage({ kind: 'ready' });
  }, []);

  // --- ask ----------------------------------------------------------------------------------
  const submitQuestion = useCallback(
    (text: string, mode: InputMode) => {
      if (!session) return;
      const question = text.trim();
      if (!question) return;
      player().stop();
      setError(null);
      setResult(null);
      setCitation(null);
      setStage({ kind: 'asking', text: question, mode });
      const wantAudio = mode === 'voice' && !lowBandwidth;
      ask({
        session_id: session.session_id,
        text: question,
        lang: locale.lang,
        script: locale.script,
        region: session.region,
        input_mode: mode,
        want_audio: wantAudio,
        low_bandwidth: lowBandwidth,
      })
        .then((response) => {
          setResult({ response, question });
          setDraft('');
          setStage({ kind: 'ready' });
          if (wantAudio && response.audio_url) {
            player()
              .play(resolveAudioUrl(response.audio_url))
              .catch(() => undefined); // autoplay can be refused; the Listen button still works
          }
        })
        .catch((err: unknown) => {
          const key = errorMessageKey(err);
          if (key === 'session_expired') {
            clearAll();
            setSession(null);
            setStage({ kind: 'consent' });
            setError({ key, retry: null });
            return;
          }
          setStage({ kind: 'ready' });
          setDraft(question);
          setError({ key, retry: () => submitQuestion(question, mode) });
        });
    },
    [session, locale, lowBandwidth, player],
  );

  // --- voice --------------------------------------------------------------------------------
  const stopAndTranscribe = useCallback(() => {
    if (!session) return;
    setStage({ kind: 'transcribing' });
    recorder()
      .stop()
      .then((rec) => {
        if (rec.blob.size < 1024 || rec.durationMs < 400) {
          setStage({ kind: 'ready' });
          setError({ key: 'transcript_empty', retry: null });
          return undefined;
        }
        return transcribe(rec.blob, rec.fileName, session.session_id, locale.lang).then((tr) => {
          const text = tr.text.trim();
          if (!text) {
            setStage({ kind: 'ready' });
            setError({ key: 'transcript_empty', retry: null });
            return;
          }
          setError(null);
          setStage({ kind: 'confirm', text });
        });
      })
      .catch((err: unknown) => {
        setStage({ kind: 'ready' });
        if (err instanceof RecorderError) {
          setError({ key: 'mic_error', retry: null });
          return;
        }
        const key = errorMessageKey(err);
        if (key === 'session_expired') {
          clearAll();
          setSession(null);
          setStage({ kind: 'consent' });
        }
        setError({ key, retry: null });
      });
  }, [session, locale.lang, recorder]);

  const handleMicPress = useCallback(() => {
    if (stage.kind === 'recording') {
      stopAndTranscribe();
      return;
    }
    if (stage.kind !== 'ready' && stage.kind !== 'confirm') return;
    player().stop();
    setError(null);
    setMicNote(null);
    recorder()
      .start(() => stopAndTranscribe())
      .then(() => setStage({ kind: 'recording' }))
      .catch((err: unknown) => {
        if (err instanceof RecorderError) {
          if (err.kind === 'unsupported') {
            setMicSupported(false);
            setMicNote('mic_unsupported');
          } else if (err.kind === 'denied') {
            setMicNote('mic_denied');
          } else {
            setMicNote('mic_error');
          }
        } else {
          setMicNote('mic_error');
        }
        setStage({ kind: 'ready' });
        textareaRef.current?.focus();
      });
  }, [stage.kind, stopAndTranscribe, player, recorder]);

  const handleConfirmNo = useCallback(() => {
    setStage({ kind: 'ready' });
  }, []);

  // --- audio for the answer -----------------------------------------------------------------
  const handleListen = useCallback(() => {
    if (!result) return;
    const { response } = result;
    setAudioBusy(true);
    setError((e) => (e?.key === 'audio_error' ? null : e));
    const playback = response.audio_url
      ? player().play(resolveAudioUrl(response.audio_url))
      : speak({ text: speakableText(response), lang: locale.lang, script: locale.script, low_bandwidth: lowBandwidth }).then(
          (blob) => player().play(blob),
        );
    playback
      .catch(() => setError({ key: 'audio_error', retry: null }))
      .finally(() => setAudioBusy(false));
  }, [result, locale, lowBandwidth, player]);

  const handleNewQuestion = useCallback(() => {
    player().stop();
    setResult(null);
    setCitation(null);
    setError(null);
    setStage({ kind: 'ready' });
    composerRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    textareaRef.current?.focus({ preventScroll: true });
  }, [player]);

  // --- delete -------------------------------------------------------------------------------
  const resetToConsent = useCallback(() => {
    recorderRef.current?.cancel();
    player().stop();
    clearAll();
    setSession(null);
    setResult(null);
    setCitation(null);
    setDraft('');
    setError(null);
    setStage({ kind: 'consent' });
  }, [player]);

  const handleDeleteData = useCallback(async (): Promise<DeleteResult> => {
    if (!session) {
      resetToConsent();
      return 'ok';
    }
    try {
      await deleteSession(session.session_id);
    } catch (err) {
      if (!(isApiError(err) && err.kind === 'http' && err.status === 404)) return 'error';
    }
    resetToConsent();
    return 'ok';
  }, [session, resetToConsent]);

  // --- derived --------------------------------------------------------------------------------
  const busy = stage.kind === 'asking' || stage.kind === 'transcribing' || stage.kind === 'recording';
  const micState: MicState = stage.kind === 'recording' ? 'recording' : stage.kind === 'transcribing' || stage.kind === 'asking' ? 'busy' : 'idle';
  const statusText =
    stage.kind === 'recording'
      ? t('recording_label')
      : stage.kind === 'transcribing'
        ? t('transcribing')
        : stage.kind === 'asking'
          ? t('thinking')
          : '';
  const citationFor = useCallback(
    (marker: string) => {
      const found = result?.response.citations.find((c) => c.marker === marker) ?? null;
      setCitation(found);
    },
    [result],
  );

  const submitDraft = () => {
    if (busy) return;
    submitQuestion(draft, 'text');
  };

  return (
    <>
      <a className="skip-link" href="#main">
        {t('skip_to_content')}
      </a>
      <div className="banner" role="note">
        {t('banner_not_advice')}
      </div>
      <header className="app-header">
        <div className="brand">{t('app_name')}</div>
        <p className="tagline">{t('tagline')}</p>
      </header>

      <main id="main" className="main">
        {stage.kind === 'boot' ? (
          <p className="status" role="status">
            {t('loading')}
          </p>
        ) : null}

        {stage.kind === 'consent' ? (
          <>
            {error ? (
              <div className="alert" role="alert">
                <p>{t(error.key)}</p>
              </div>
            ) : null}
            <ConsentDialog
              locale={locale}
              onLocaleChange={handleLocaleChange}
              initialRegion={session?.region ?? 'BA'}
              lowBandwidth={lowBandwidth}
              player={player()}
              onDone={handleConsentDone}
            />
          </>
        ) : null}

        {stage.kind !== 'boot' && stage.kind !== 'consent' ? (
          <>
            <section ref={composerRef} className="composer" aria-label={t('ask_placeholder')}>
              {micSupported ? (
                <MicButton
                  state={micState}
                  disabled={stage.kind === 'asking' || stage.kind === 'transcribing'}
                  seconds={seconds}
                  labels={{ start: t('mic_start'), stop: t('mic_stop'), recording: t('recording_label') }}
                  onPress={handleMicPress}
                />
              ) : null}
              {micSupported === false ? <p className="muted">{t(micNote ?? 'mic_unsupported')}</p> : null}
              {micSupported && micNote ? (
                <p className="muted" role="alert">
                  {t(micNote)}
                </p>
              ) : null}

              <p className="status" role="status" aria-live="polite">
                {busy && stage.kind !== 'recording' ? <span className="spinner" aria-hidden="true" /> : null}
                {statusText}
              </p>

              {stage.kind === 'confirm' ? (
                <TranscriptConfirm
                  text={stage.text}
                  locale={locale}
                  onYes={(text) => submitQuestion(text, 'voice')}
                  onNo={handleConfirmNo}
                />
              ) : null}

              <form
                className="composer-form"
                onSubmit={(ev) => {
                  ev.preventDefault();
                  submitDraft();
                }}
              >
                <label htmlFor="question" className="visually-hidden">
                  {t('ask_placeholder')}
                </label>
                <textarea
                  id="question"
                  ref={textareaRef}
                  className="textarea"
                  rows={2}
                  maxLength={2000}
                  placeholder={t('ask_placeholder')}
                  value={draft}
                  disabled={busy}
                  autoComplete="off"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      submitDraft();
                    }
                  }}
                />
                <button type="submit" className="btn btn--primary" disabled={busy || draft.trim().length === 0}>
                  {t('send')}
                </button>
              </form>
            </section>

            {error ? (
              <div className="alert" role="alert">
                <p>{t(error.key)}</p>
                <div className="row">
                  {error.retry ? (
                    <button type="button" className="btn btn--primary" onClick={error.retry}>
                      {t('retry')}
                    </button>
                  ) : null}
                  <button type="button" className="btn btn--ghost" onClick={() => setError(null)}>
                    {t('dismiss')}
                  </button>
                </div>
              </div>
            ) : null}

            <div ref={resultRef} aria-live="polite">
              {result ? (
                result.response.outcome === 'redflag' ? (
                  <EmergencyCard response={result.response} locale={locale} onNewQuestion={handleNewQuestion} />
                ) : (
                  <AnswerView
                    response={result.response}
                    question={result.question}
                    locale={locale}
                    playing={playerState === 'playing'}
                    audioBusy={audioBusy || playerState === 'loading'}
                    onListen={handleListen}
                    onStopAudio={() => player().stop()}
                    onCitation={citationFor}
                    onNewQuestion={handleNewQuestion}
                  />
                )
              ) : null}
            </div>
          </>
        ) : null}
      </main>

      <Footer
        locale={locale}
        onLocaleChange={handleLocaleChange}
        lowBandwidth={lowBandwidth}
        onLowBandwidthChange={handleLowBandwidth}
        hasSession={session !== null}
        onDeleteData={handleDeleteData}
        onDeleteLocalOnly={resetToConsent}
      />

      <CitationSheet citation={citation} locale={locale} onClose={() => setCitation(null)} />
    </>
  );
}
