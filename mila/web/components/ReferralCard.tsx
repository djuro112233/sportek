'use client';

import { referralKindKey, translator } from '@/lib/i18n';
import type { Locale, Referral, ReferralPoint } from '@/lib/types';

interface Props {
  referral: Referral;
  locale: Locale;
  emergency?: boolean;
  title?: string;
  /** Hide `referral.message` when the parent already showed the same text (red-flag card). */
  hideMessage?: boolean;
}

/** Digits and a leading "+" only, so tel: links work with spaces, slashes or dashes in the data. */
export function telHref(phone: string): string {
  const cleaned = phone.trim().replace(/[^\d+]/g, '');
  const normalized = cleaned.startsWith('+') ? `+${cleaned.slice(1).replace(/\+/g, '')}` : cleaned.replace(/\+/g, '');
  return `tel:${normalized}`;
}

function safeHttpUrl(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** Emergency numbers are standard; every other point counts as verified only with a `verified_on` date. */
export function isUnverified(point: ReferralPoint): boolean {
  return !point.emergency && (point.verified_on ?? '').trim() === '';
}

/**
 * One referral point. Only name, kind, address, hours, a call button (when a phone exists) and a
 * website link are shown; internal fields never reach the screen.
 */
function Point({ point, locale, emergency }: { point: ReferralPoint; locale: Locale; emergency: boolean }) {
  const t = translator(locale);
  const phone = (point.phone ?? '').trim();
  const url = safeHttpUrl(point.url);
  const isEmergency = emergency || Boolean(point.emergency);
  const place = [point.address, point.city].filter((s) => s && s.trim()).join(', ');
  const unverified = isUnverified(point);

  return (
    <li className={isEmergency ? 'referral__point referral__point--emergency' : 'referral__point'}>
      <div className="referral__name">{point.name}</div>
      <div className="referral__kind">{t(referralKindKey(point.kind))}</div>
      {place ? <div className="referral__detail">{place}</div> : null}
      {point.hours ? (
        <div className="referral__detail">
          {t('hours')}: {point.hours}
        </div>
      ) : null}
      {unverified ? <div className="badge badge--warn referral__unverified">{t('unverified_contact')}</div> : null}
      {phone || url ? (
        <div className="row">
          {phone ? (
            <a className={isEmergency ? 'btn btn--danger' : 'btn btn--primary'} href={telHref(phone)}>
              {t('call')} {phone}
            </a>
          ) : null}
          {url ? (
            <a className="btn btn--ghost" href={url} target="_blank" rel="noopener noreferrer">
              {t('website')}
            </a>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export default function ReferralCard({ referral, locale, emergency = false, title, hideMessage = false }: Props) {
  const t = translator(locale);
  const isEmergency = emergency || referral.emergency;
  // Emergency points first so the most important number is at the top on a small screen.
  const points = [...referral.points].sort((a, b) => Number(Boolean(b.emergency)) - Number(Boolean(a.emergency)));

  return (
    <section className={isEmergency ? 'card card--danger stack' : 'card stack'} aria-label={title ?? t('referral_title')}>
      <h3>{title ?? t('referral_title')}</h3>
      {referral.message && !hideMessage ? <p>{referral.message}</p> : null}
      {points.length > 0 ? (
        <ul className="referral__list">
          {points.map((p, i) => (
            <Point key={`${p.name}-${i}`} point={p} locale={locale} emergency={isEmergency} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
