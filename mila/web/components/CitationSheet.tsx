'use client';

import { useEffect, useRef } from 'react';

import { reviewStatusKey, translator } from '@/lib/i18n';
import type { Citation, Locale } from '@/lib/types';

interface Props {
  citation: Citation | null;
  locale: Locale;
  onClose: () => void;
}

/** Bottom sheet with the source behind a [S1] chip. Escape or backdrop tap closes it. */
export default function CitationSheet({ citation, locale, onClose }: Props) {
  const t = translator(locale);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<Element | null>(null);

  useEffect(() => {
    if (!citation) return undefined;
    previousFocus.current = document.activeElement;
    closeRef.current?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      const prev = previousFocus.current;
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, [citation, onClose]);

  if (!citation) return null;

  const rows: Array<[string, string]> = [
    [t('citation_source'), citation.source_title],
    [t('citation_section'), citation.section],
    [t('citation_version'), citation.version],
    [t('citation_date'), citation.date],
    [t('citation_page'), citation.page === null || citation.page === undefined ? '' : String(citation.page)],
    [t('citation_status'), t(reviewStatusKey(citation.review_status))],
  ];

  return (
    <div
      className="sheet-backdrop"
      onClick={(ev) => {
        if (ev.target === ev.currentTarget) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="citation-title">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 id="citation-title">
            [{citation.marker}] {t('citation_title')}
          </h2>
          <button ref={closeRef} type="button" className="btn btn--ghost" onClick={onClose}>
            {t('close')}
          </button>
        </div>
        <dl className="sheet__grid">
          {rows
            .filter(([, value]) => value && value.trim().length > 0)
            .map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
        {citation.review_status !== 'reviewed' ? (
          <p className="badge badge--warn">{t('status_public_unreviewed')}</p>
        ) : (
          <p className="badge badge--ok">{t('status_reviewed')}</p>
        )}
      </div>
    </div>
  );
}
