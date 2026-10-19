'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { errorMessageKey, getConsentText, postConsent, speak } from '@/lib/api';
import { LANGUAGE_OPTIONS, localeId, translator, type MsgKey } from '@/lib/i18n';
import type { ConsentItem, ConsentText, Locale, Region, StoredSession } from '@/lib/types';
import { SUPPORTED_REGIONS } from '@/lib/types';
import type { Player, PlayerState } from '@/lib/voice';

interface Props {
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
  initialRegion: Region;
  lowBandwidth: boolean;
  player: Player;
  onDone: (session: StoredSession) => void;
}

function itemText(item: ConsentItem): string {
  if (typeof item === 'string') return item;
  return item.text ?? item.label ?? '';
}

/** First-visit screen: language, under-18, region, consent text (+ Listen), save toggle, I agree. */
export default function ConsentDialog({ locale, onLocaleChange, initialRegion, lowBandwidth, player, onDone }: Props) {
  const t = translator(locale);
  const [isMinor, setIsMinor] = useState<boolean | null>(null);
  const [region, setRegion] = useState<Region>(initialRegion);
  const [saveQuestions, setSaveQuestions] = useState(false);
  const [consent, setConsent] = useState<ConsentText | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<MsgKey | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<MsgKey | null>(null);
  const [needMinor, setNeedMinor] = useState(false);
  const [playerState, setPlayerState] = useState<PlayerState>('idle');
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const minorGroupRef = useRef<HTMLDivElement>(null);

  useEffect(() => player.subscribe(setPlayerState), [player]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    getConsentText(locale, isMinor ?? false, controller.signal)
      .then((data) => {
        setConsent(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(errorMessageKey(err));
        setLoading(false);
      });
    return () => controller.abort();
  }, [locale, isMinor, reloadToken]);

  useEffect(() => () => player.stop(), [player]);

  const listen = useCallback(async () => {
    if (!consent) return;
    setAudioError(false);
    setAudioBusy(true);
    try {
      const blob = await speak({
        text: consent.spoken_text || consent.text,
        lang: locale.lang,
        script: locale.script,
        low_bandwidth: lowBandwidth,
      });
      await player.play(blob);
    } catch {
      setAudioError(true);
    } finally {
      setAudioBusy(false);
    }
  }, [consent, locale, lowBandwidth, player]);

  const agree = useCallback(async () => {
    if (!consent) return;
    if (isMinor === null) {
      setNeedMinor(true);
      minorGroupRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await postConsent({
        lang: locale.lang,
        script: locale.script,
        region,
        is_minor: isMinor,
        accepted: true,
        save_questions: saveQuestions,
        consent_version: consent.version,
      });
      player.stop();
      onDone({ session_id: res.session_id, lang: locale.lang, script: locale.script, region, is_minor: isMinor });
    } catch (err) {
      setSubmitError(errorMessageKey(err));
      setSubmitting(false);
    }
  }, [consent, isMinor, locale, region, saveQuestions, player, onDone]);

  const playing = playerState === 'playing' || playerState === 'loading';
  const paragraphs = consent ? consent.text.split(/\n+/).map((p) => p.trim()).filter(Boolean) : [];

  return (
    <section className="card stack" aria-labelledby="consent-title">
      <h1 id="consent-title">{t('consent_title')}</h1>
      <p className="muted">{t('consent_intro')}</p>

      <div>
        <div className="field-label" id="consent-language-label">
          {t('consent_language')}
        </div>
        <div className="choice-grid" role="radiogroup" aria-labelledby="consent-language-label">
          {LANGUAGE_OPTIONS.map((o) => {
            const selected = localeId(locale) === o.id;
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                lang={o.htmlLang}
                aria-checked={selected}
                className="choice"
                onClick={() => onLocaleChange({ lang: o.lang, script: o.script })}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      </div>

      <div ref={minorGroupRef} tabIndex={-1}>
        <div className="field-label" id="consent-minor-label">
          {t('consent_minor_q')}
        </div>
        <div className="choice-grid" role="radiogroup" aria-labelledby="consent-minor-label" aria-required="true">
          <button
            type="button"
            role="radio"
            aria-checked={isMinor === true}
            className="choice"
            onClick={() => {
              setIsMinor(true);
              setNeedMinor(false);
            }}
          >
            {t('yes')}
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={isMinor === false}
            className="choice"
            onClick={() => {
              setIsMinor(false);
              setNeedMinor(false);
            }}
          >
            {t('no')}
          </button>
        </div>
        {needMinor ? (
          <p className="muted" role="alert" style={{ marginTop: 6 }}>
            {t('consent_need_minor')}
          </p>
        ) : null}
      </div>

      <div>
        <div className="field-label" id="consent-region-label">
          {t('consent_region')}
        </div>
        <div className="choice-grid" role="radiogroup" aria-labelledby="consent-region-label">
          {SUPPORTED_REGIONS.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={region === r}
              className="choice"
              onClick={() => setRegion(r)}
            >
              {t(r === 'BA' ? 'region_BA' : 'region_ME')}
            </button>
          ))}
        </div>
      </div>

      <div className="card card--soft stack" aria-live="polite">
        {loading ? (
          <p className="status" role="status">
            <span className="spinner" aria-hidden="true" />
            {t('loading')}
          </p>
        ) : null}
        {loadError ? (
          <div className="alert" role="alert">
            <p>{t(loadError)}</p>
            <button type="button" className="btn btn--primary" onClick={() => setReloadToken((n) => n + 1)}>
              {t('retry')}
            </button>
          </div>
        ) : null}
        {consent && !loading ? (
          <>
            {paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            {consent.items.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: '1.2em' }}>
                {consent.items.map((item, i) => {
                  const text = itemText(item);
                  return text ? <li key={i}>{text}</li> : null;
                })}
              </ul>
            ) : null}
            <div className="row">
              {playing ? (
                <button type="button" className="btn btn--secondary" onClick={() => player.stop()}>
                  {t('stop')}
                </button>
              ) : (
                <button type="button" className="btn btn--secondary" disabled={audioBusy} onClick={() => void listen()}>
                  {audioBusy ? t('playing') : t('listen')}
                </button>
              )}
              {audioError ? (
                <span className="muted" role="alert">
                  {t('audio_error')}
                </span>
              ) : null}
            </div>
          </>
        ) : null}
      </div>

      <label className="toggle">
        <input type="checkbox" checked={saveQuestions} onChange={(e) => setSaveQuestions(e.target.checked)} />
        <span>
          <strong>{t('consent_save_questions')}</strong>
          <br />
          <span className="muted">{t('consent_save_hint')}</span>
        </span>
      </label>

      {submitError ? (
        <div className="alert" role="alert">
          <p>{t(submitError)}</p>
        </div>
      ) : null}

      <button
        type="button"
        className="btn btn--primary btn--block"
        disabled={!consent || loading || submitting}
        onClick={() => void agree()}
      >
        {submitting ? t('loading') : t('consent_agree')}
      </button>
      {consent ? (
        <p className="muted">
          {t('citation_version')}: {consent.version}
        </p>
      ) : null}
    </section>
  );
}
