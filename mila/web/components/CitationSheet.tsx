'use client';

import { useEffect, useRef } from 'react';

import { reviewStatusKey, translator } from '@/lib/i18n';
import type { Citation, Locale } from '@/lib/types';

interface Props {
  citation: Citation | null;
  locale: Locale;
  onClose: () => void;
}

/**
 * Bottom sheet with the source behind a [S1] chip. A native <dialog> opened with showModal()
 * traps focus and makes the rest of the page inert; Escape (the dialog's cancel event) or a tap
 * on the backdrop closes it, and focus returns to the chip that opened it.
 */
export default function CitationSheet({ citation, locale, onClose }: Props) {
  const t = translator(locale);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<Element | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!citation || !dialog) return undefined;
    previousFocus.current = document.activeElement;
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') {
        try {
          dialog.showModal();
        } catch {
          dialog.setAttribute('open', '');
        }
      } else {
        dialog.setAttribute('open', '');
      }
    }
    closeRef.current?.focus();
    // Escape: the modal dialog fires `cancel`; the keydown fallback covers browsers without showModal.
    const onCancel = (ev: Event) => {
      ev.preventDefault();
      onClose();
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        onClose();
      }
    };
    dialog.addEventListener('cancel', onCancel);
    dialog.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.removeEventListener('cancel', onCancel);
      dialog.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      if (dialog.open && typeof dialog.close === 'function') {
        try {
          dialog.close();
        } catch {
          // already closed
        }
      }
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
    <dialog
      ref={dialogRef}
      className="sheet-dialog"
      aria-modal="true"
      aria-labelledby="citation-title"
      onClick={(ev) => {
        // A click on the ::backdrop targets the dialog element itself; clicks inside hit .sheet.
        if (ev.target === ev.currentTarget) onClose();
      }}
    >
      <div className="sheet">
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
    </dialog>
  );
}
