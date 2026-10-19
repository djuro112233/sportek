'use client';

import { useEffect, useRef, useState } from 'react';

import { translator } from '@/lib/i18n';
import type { Locale } from '@/lib/types';

interface Props {
  text: string;
  locale: Locale;
  onYes: (text: string) => void;
  onNo: () => void;
}

/** "I heard: ... Is this right?" with Yes / No / Edit. Edit turns the quote into a text box. */
export default function TranscriptConfirm({ text, locale, onYes, onNo }: Props) {
  const t = translator(locale);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setDraft(text);
    setEditing(false);
    headingRef.current?.focus();
  }, [text]);

  useEffect(() => {
    if (editing) textareaRef.current?.focus();
  }, [editing]);

  const trimmed = draft.trim();

  return (
    <section className="card card--soft stack" aria-labelledby="transcript-heading">
      <h2 id="transcript-heading" ref={headingRef} tabIndex={-1}>
        {t('heard')}
      </h2>
      {editing ? (
        <textarea
          ref={textareaRef}
          className="textarea"
          rows={3}
          maxLength={2000}
          value={draft}
          aria-label={t('edit')}
          onChange={(e) => setDraft(e.target.value)}
        />
      ) : (
        <blockquote style={{ margin: 0, fontSize: '1.1rem' }}>{text}</blockquote>
      )}
      <p>{t('is_this_right')}</p>
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={trimmed.length === 0} onClick={() => onYes(trimmed)}>
          {t('yes')}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onNo}>
          {t('no_try_again')}
        </button>
        {!editing ? (
          <button type="button" className="btn btn--secondary" onClick={() => setEditing(true)}>
            {t('edit')}
          </button>
        ) : null}
      </div>
    </section>
  );
}
