'use client';

import { useEffect, useRef } from 'react';

import ReferralCard from '@/components/ReferralCard';
import { confidenceKey, translator } from '@/lib/i18n';
import type { AskResponse, Locale } from '@/lib/types';

interface Props {
  response: AskResponse;
  question: string;
  locale: Locale;
  playing: boolean;
  audioBusy: boolean;
  onListen: () => void;
  onStopAudio: () => void;
  onCitation: (marker: string) => void;
  onNewQuestion: () => void;
}

/** Answered or withheld outcome. Red flags are rendered by EmergencyCard instead. */
export default function AnswerView({
  response,
  question,
  locale,
  playing,
  audioBusy,
  onListen,
  onStopAudio,
  onCitation,
  onNewQuestion,
}: Props) {
  const t = translator(locale);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const withheld = response.outcome === 'withheld';
  const sentences = response.sentences.filter((s) => s.text.trim().length > 0);
  const hasSpeakable = withheld ? response.message.trim().length > 0 : sentences.length > 0;
  const knownMarkers = new Set(response.citations.map((c) => c.marker));

  useEffect(() => {
    headingRef.current?.focus();
  }, [response]);

  return (
    <section className="card stack" aria-labelledby="answer-title">
      <div className="question">
        <div className="question__label">{t('you_asked')}</div>
        <div>{question}</div>
      </div>

      <h2 id="answer-title" ref={headingRef} tabIndex={-1}>
        {withheld ? t('withheld_title') : t('answer_title')}
      </h2>

      {withheld ? (
        response.message ? <p>{response.message}</p> : null
      ) : (
        <>
          {response.demo_unreviewed_sources ? <p className="badge badge--warn">{t('demo_badge')}</p> : null}
          <ol className="sentences">
            {sentences.map((s, i) => (
              <li key={i} className="sentence">
                <span>{s.text}</span>
                {s.citations.map((marker) => (
                  <button
                    key={marker}
                    type="button"
                    className="chip"
                    aria-label={`${t('citation_title')} ${marker}`}
                    disabled={!knownMarkers.has(marker)}
                    onClick={() => onCitation(marker)}
                  >
                    [{marker}]
                  </button>
                ))}
              </li>
            ))}
          </ol>
          <div className="meta">
            <span>
              {t('confidence')}: <strong>{t(confidenceKey(response.confidence))}</strong>
            </span>
            {response.translated ? <span>{t('translated_note')}</span> : null}
          </div>
        </>
      )}

      <div className="row">
        {hasSpeakable ? (
          playing ? (
            <button type="button" className="btn btn--secondary" onClick={onStopAudio}>
              {t('stop')}
            </button>
          ) : (
            <button type="button" className="btn btn--secondary" disabled={audioBusy} onClick={onListen}>
              {audioBusy ? t('playing') : t('listen')}
            </button>
          )
        ) : null}
        <button type="button" className="btn btn--ghost" onClick={onNewQuestion}>
          {t('new_question')}
        </button>
      </div>

      {response.disclaimer_short ? <p className="disclaimer">{response.disclaimer_short}</p> : null}

      {response.referral && (withheld || response.referral.points.length > 0) ? (
        <ReferralCard referral={response.referral} locale={locale} />
      ) : null}
    </section>
  );
}
