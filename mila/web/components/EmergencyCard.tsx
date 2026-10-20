'use client';

import { useEffect, useRef } from 'react';

import ReferralCard from '@/components/ReferralCard';
import { translator } from '@/lib/i18n';
import type { AskResponse, Locale } from '@/lib/types';

interface Props {
  response: AskResponse;
  locale: Locale;
  playing: boolean;
  audioBusy: boolean;
  onListen: () => void;
  onStopAudio: () => void;
  onNewQuestion: () => void;
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path d="M32 6 2 58h60L32 6z" fill="#b91c1c" />
      <path d="M32 24v16" stroke="#fff" strokeWidth="6" strokeLinecap="round" />
      <circle cx="32" cy="49" r="3.5" fill="#fff" />
    </svg>
  );
}

/** Red-flag outcome: Listen right under the title, the message once, call buttons, no answer text. */
export default function EmergencyCard({ response, locale, playing, audioBusy, onListen, onStopAudio, onNewQuestion }: Props) {
  const t = translator(locale);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // The backend sets `message` to the referral's instruction; show whichever exists, exactly once.
  const message = (response.message || response.referral?.message || '').trim();
  const minorNote = (response.minor_note || '').trim();

  useEffect(() => {
    titleRef.current?.focus();
  }, [response]);

  return (
    <section className="emergency" role="alert" aria-labelledby="emergency-title">
      <h2 id="emergency-title" className="emergency__title" ref={titleRef} tabIndex={-1}>
        <WarningIcon />
        {t('emergency_title')}
      </h2>
      {message ? (
        <div className="row">
          {playing ? (
            <button type="button" className="btn btn--secondary" onClick={onStopAudio}>
              {t('stop')}
            </button>
          ) : (
            <button type="button" className="btn btn--secondary" disabled={audioBusy} onClick={onListen}>
              {audioBusy ? t('playing') : t('listen')}
            </button>
          )}
        </div>
      ) : null}
      {message ? <p className="emergency__message">{message}</p> : null}
      {minorNote ? <p className="minor-note">{minorNote}</p> : null}
      {response.referral ? <ReferralCard referral={response.referral} locale={locale} emergency hideMessage /> : null}
      {response.disclaimer_short ? <p className="disclaimer">{response.disclaimer_short}</p> : null}
      <button type="button" className="btn btn--ghost" onClick={onNewQuestion}>
        {t('new_question')}
      </button>
    </section>
  );
}
