'use client';

import { useState } from 'react';

import { LANGUAGE_OPTIONS, localeFromId, localeId, translator } from '@/lib/i18n';
import type { Locale } from '@/lib/types';

export type DeleteResult = 'ok' | 'error';

interface Props {
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
  lowBandwidth: boolean;
  onLowBandwidthChange: (value: boolean) => void;
  hasSession: boolean;
  onDeleteData: () => Promise<DeleteResult>;
  onDeleteLocalOnly: () => void;
}

type DeleteStage = 'idle' | 'confirm' | 'working' | 'done' | 'error';

export default function Footer({
  locale,
  onLocaleChange,
  lowBandwidth,
  onLowBandwidthChange,
  hasSession,
  onDeleteData,
  onDeleteLocalOnly,
}: Props) {
  const t = translator(locale);
  const [stage, setStage] = useState<DeleteStage>('idle');

  const runDelete = async () => {
    setStage('working');
    const result = await onDeleteData();
    setStage(result === 'ok' ? 'done' : 'error');
  };

  return (
    <footer className="footer">
      <div className="footer__row">
        <label className="field-label" htmlFor="footer-language" style={{ marginBottom: 0 }}>
          {t('language')}
        </label>
        <select
          id="footer-language"
          className="select"
          value={localeId(locale)}
          onChange={(e) => onLocaleChange(localeFromId(e.target.value))}
        >
          {LANGUAGE_OPTIONS.map((o) => (
            <option key={o.id} value={o.id} lang={o.htmlLang}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <label className="toggle">
        <input type="checkbox" checked={lowBandwidth} onChange={(e) => onLowBandwidthChange(e.target.checked)} />
        <span>
          <strong>{t('low_bandwidth')}</strong>
          <br />
          <span className="muted">{t('low_bandwidth_hint')}</span>
        </span>
      </label>

      {hasSession ? (
        <div className="stack">
          {stage === 'idle' ? (
            <button type="button" className="btn btn--ghost" onClick={() => setStage('confirm')}>
              {t('delete_data')}
            </button>
          ) : null}
          {stage === 'confirm' ? (
            <div className="alert" role="group" aria-label={t('delete_data')}>
              <p>{t('delete_confirm')}</p>
              <div className="row">
                <button type="button" className="btn btn--danger" onClick={() => void runDelete()}>
                  {t('delete')}
                </button>
                <button type="button" className="btn btn--ghost" onClick={() => setStage('idle')}>
                  {t('cancel')}
                </button>
              </div>
            </div>
          ) : null}
          {stage === 'working' ? (
            <p className="status" role="status">
              <span className="spinner" aria-hidden="true" />
              {t('loading')}
            </p>
          ) : null}
          {stage === 'error' ? (
            <div className="alert" role="alert">
              <p>{t('delete_error')}</p>
              <div className="row">
                <button type="button" className="btn btn--primary" onClick={() => void runDelete()}>
                  {t('retry')}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => {
                    onDeleteLocalOnly();
                    setStage('done');
                  }}
                >
                  {t('delete_local_only')}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      {stage === 'done' ? (
        <p className="badge badge--ok" role="status">
          {t('delete_done')}
        </p>
      ) : null}

      <p className="muted">{t('not_advice_long')}</p>
      <p className="muted">
        {t('open_source')} Apache-2.0.
      </p>
    </footer>
  );
}
