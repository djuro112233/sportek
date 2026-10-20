/**
 * UI strings and script handling for MILA.
 *
 * Catalogue languages: sr (Latin), bs, me, hr, en. Serbian Cyrillic (and Cyrillic for any
 * BCMS language) is produced at render time by `latinToCyrillic`, which mirrors
 * `backend/app/core/i18n.py` (digraphs lj / nj / dž are replaced before single letters).
 *
 * Copy rules: short, plain, second person singular, readable by a 15-year-old.
 * Keep Latin-only letters (w, x, y, q) out of BCMS strings so transliteration stays clean.
 */

import type { Lang, Locale, Script } from './types';

// --- transliteration ---------------------------------------------------------------------

const LAT_TO_CYR_DIGRAPHS: ReadonlyArray<readonly [string, string]> = [
  ['lj', 'љ'],
  ['nj', 'њ'],
  ['dž', 'џ'],
  ['Lj', 'Љ'],
  ['Nj', 'Њ'],
  ['Dž', 'Џ'],
  ['LJ', 'Љ'],
  ['NJ', 'Њ'],
  ['DŽ', 'Џ'],
];

const LAT_TO_CYR: Readonly<Record<string, string>> = {
  a: 'а', b: 'б', v: 'в', g: 'г', d: 'д', đ: 'ђ', e: 'е', ž: 'ж', z: 'з',
  i: 'и', j: 'ј', k: 'к', l: 'л', m: 'м', n: 'н', o: 'о', p: 'п', r: 'р',
  s: 'с', t: 'т', ć: 'ћ', u: 'у', f: 'ф', h: 'х', c: 'ц', č: 'ч', š: 'ш',
};

const BCMS_LANGS: readonly Lang[] = ['sr', 'bs', 'hr', 'me'];

export function isBcms(lang: string): boolean {
  return (BCMS_LANGS as readonly string[]).includes(lang);
}

/** Serbian Latin -> Cyrillic. Digraphs first (lj, nj, dž), then single letters. */
export function latinToCyrillic(text: string): string {
  let out = text;
  for (const [dg, cy] of LAT_TO_CYR_DIGRAPHS) {
    out = out.split(dg).join(cy);
  }
  let result = '';
  for (const ch of out) {
    const low = ch.toLowerCase();
    const cy = LAT_TO_CYR[low];
    if (cy !== undefined) {
      result += ch === low ? cy : cy.toUpperCase();
    } else {
      result += ch;
    }
  }
  return result;
}

/** Apply the requested output script. Cyrillic is only meaningful for BCMS languages. */
export function render(text: string, lang: string, script: Script): string {
  if (script === 'cyrillic' && isBcms(lang)) {
    return latinToCyrillic(text);
  }
  return text;
}

// --- language options ----------------------------------------------------------------------

export type LocaleId = 'sr' | 'sr-Cyrl' | 'bs' | 'me' | 'hr' | 'en';

export interface LanguageOption {
  id: LocaleId;
  lang: Lang;
  script: Script;
  label: string; // native name, shown as-is (never transliterated)
  htmlLang: string; // value for <html lang>
}

export const LANGUAGE_OPTIONS: readonly LanguageOption[] = [
  { id: 'sr', lang: 'sr', script: 'latin', label: 'Srpski (latinica)', htmlLang: 'sr-Latn' },
  { id: 'sr-Cyrl', lang: 'sr', script: 'cyrillic', label: 'Српски (ћирилица)', htmlLang: 'sr-Cyrl' },
  { id: 'bs', lang: 'bs', script: 'latin', label: 'Bosanski', htmlLang: 'bs' },
  { id: 'me', lang: 'me', script: 'latin', label: 'Crnogorski', htmlLang: 'cnr' },
  { id: 'hr', lang: 'hr', script: 'latin', label: 'Hrvatski', htmlLang: 'hr' },
  { id: 'en', lang: 'en', script: 'latin', label: 'English', htmlLang: 'en' },
];

export const DEFAULT_LOCALE: Locale = { lang: 'sr', script: 'latin' };

export function localeId(locale: Locale): LocaleId {
  const found = LANGUAGE_OPTIONS.find((o) => o.lang === locale.lang && o.script === locale.script);
  if (found) return found.id;
  // Cyrillic for a non-Serbian BCMS language is valid for rendering but has no picker entry.
  const byLang = LANGUAGE_OPTIONS.find((o) => o.lang === locale.lang);
  return byLang ? byLang.id : 'sr';
}

export function localeFromId(id: string): Locale {
  const found = LANGUAGE_OPTIONS.find((o) => o.id === id);
  return found ? { lang: found.lang, script: found.script } : { ...DEFAULT_LOCALE };
}

export function htmlLang(locale: Locale): string {
  const found = LANGUAGE_OPTIONS.find((o) => o.lang === locale.lang && o.script === locale.script);
  if (found) return found.htmlLang;
  const byLang = LANGUAGE_OPTIONS.find((o) => o.lang === locale.lang);
  return byLang ? byLang.htmlLang : 'sr';
}

/** Best-effort initial language from the browser, used only before the user picks one. */
export function detectLocale(navigatorLanguages: readonly string[] | undefined): Locale {
  for (const raw of navigatorLanguages ?? []) {
    const tag = raw.toLowerCase();
    if (tag.startsWith('sr')) return { lang: 'sr', script: tag.includes('cyrl') ? 'cyrillic' : 'latin' };
    if (tag.startsWith('bs')) return { lang: 'bs', script: 'latin' };
    if (tag.startsWith('hr')) return { lang: 'hr', script: 'latin' };
    if (tag.startsWith('cnr') || tag.startsWith('me')) return { lang: 'me', script: 'latin' };
    if (tag.startsWith('en')) return { lang: 'en', script: 'latin' };
  }
  return { ...DEFAULT_LOCALE };
}

// --- catalogue -----------------------------------------------------------------------------

const en = {
  app_name: 'MILA',
  tagline: 'Ask about periods, pregnancy, contraception and your body. Private and free.',
  banner_not_advice: 'Information only, not medical advice. In an emergency, call emergency services.',
  skip_to_content: 'Skip to content',

  consent_title: 'Before we start',
  consent_intro: 'Pick your language and read (or listen to) how MILA works.',
  consent_language: 'Language',
  consent_minor_q: 'Are you under 18?',
  yes: 'Yes',
  no: 'No',
  consent_region: 'Where are you?',
  region_BA: 'Bosnia and Herzegovina',
  region_ME: 'Montenegro',
  listen: 'Listen',
  stop: 'Stop',
  consent_save_questions: 'Save my questions',
  consent_save_hint: 'Off unless you turn it on. You can delete them any time.',
  consent_agree: 'I agree',
  consent_need_minor: 'First tell me if you are under 18.',

  loading: 'Loading…',
  error_network: 'No connection. Check your internet and try again.',
  error_timeout: 'This is taking too long. Try again.',
  error_server: 'Something went wrong on our side. Try again.',
  session_expired: 'Your session has ended. Please agree again to continue.',
  error_rate_limited: 'Too many questions in a short time. Wait a moment and try again.',
  consent_text_changed: 'The consent text has changed. Please read the new text and agree again.',
  retry: 'Try again',
  cancel: 'Cancel',
  dismiss: 'OK',

  ask_placeholder: 'Type your question…',
  send: 'Send',
  mic_start: 'Press to speak',
  mic_stop: 'Press to stop',
  recording_label: 'Recording… press again to stop.',
  mic_unsupported: 'Voice is not available in this browser. You can type your question.',
  mic_denied: 'Microphone access was blocked. You can type your question.',
  mic_error: 'The microphone did not work. You can type your question.',
  transcribing: 'Turning your voice into text…',
  thinking: 'Looking for an answer…',
  transcript_empty: 'I could not hear anything. Try again, closer to the phone.',

  heard: 'I heard:',
  is_this_right: 'Is this right?',
  no_try_again: 'No, try again',
  edit: 'Edit',
  you_asked: 'Your question:',
  answer_title: 'Answer',

  sources: 'Sources',
  translated_note: 'Translated from the original source.',
  demo_badge: 'Demo: sources not reviewed yet',
  confidence: 'Confidence',
  confidence_low: 'low',
  confidence_medium: 'medium',
  confidence_high: 'high',
  playing: 'Playing…',
  audio_error: 'Could not play the audio.',

  withheld_title: "I don't know this. Here is where to get help.",
  emergency_title: 'This may be an emergency',
  call: 'Call',
  website: 'Website',
  hours: 'Hours',
  referral_title: 'Where to get help',
  unverified_contact: 'Contact not yet verified',

  citation_title: 'Source',
  citation_source: 'Title',
  citation_section: 'Section',
  citation_version: 'Version',
  citation_date: 'Date',
  citation_page: 'Page',
  citation_status: 'Review status',
  status_reviewed: 'Reviewed by a clinician',
  status_public_unreviewed: 'Public, not reviewed yet',
  status_blocked: 'Not approved',
  close: 'Close',

  language: 'Language',
  low_bandwidth: 'Low data mode',
  low_bandwidth_hint: 'Smaller audio, no automatic playback.',
  delete_data: 'Delete my data',
  delete_confirm: 'Delete everything about this session? This cannot be undone.',
  delete: 'Delete',
  delete_done: 'Your data was deleted.',
  delete_local_only: 'Delete only on this phone',
  delete_error: 'Could not reach the server to delete your data.',
  new_question: 'New question',
  not_advice_long:
    'MILA gives general information and tells you where to get help. It does not diagnose, prescribe or read test results. If you feel unwell, see a clinician.',
  open_source: 'Open source. No tracking.',

  kind_clinic: 'Clinic',
  kind_er: 'Emergency',
  kind_helpline: 'Helpline',
  kind_child_protection: 'Child protection',
  kind_violence: 'Help with violence',
  kind_mental_health: 'Mental health',
  kind_other: 'Service',
} as const;

export type MsgKey = keyof typeof en;
export type Catalogue = Record<MsgKey, string>;

const sr: Catalogue = {
  app_name: 'MILA',
  tagline: 'Pitaj o menstruaciji, trudnoći, kontracepciji i svom tijelu. Privatno i besplatno.',
  banner_not_advice: 'Samo informacije, ne medicinski savjet. U hitnom slučaju pozovi hitnu pomoć.',
  skip_to_content: 'Preskoči na sadržaj',

  consent_title: 'Prije nego počnemo',
  consent_intro: 'Izaberi jezik i pročitaj (ili poslušaj) kako MILA radi.',
  consent_language: 'Jezik',
  consent_minor_q: 'Imaš li manje od 18 godina?',
  yes: 'Da',
  no: 'Ne',
  consent_region: 'Gdje se nalaziš?',
  region_BA: 'Bosna i Hercegovina',
  region_ME: 'Crna Gora',
  listen: 'Poslušaj',
  stop: 'Zaustavi',
  consent_save_questions: 'Sačuvaj moja pitanja',
  consent_save_hint: 'Isključeno je dok ti ne uključiš. Možeš ih obrisati kad god želiš.',
  consent_agree: 'Slažem se',
  consent_need_minor: 'Prvo mi reci imaš li manje od 18 godina.',

  loading: 'Učitavanje…',
  error_network: 'Nema veze. Provjeri internet i pokušaj ponovo.',
  error_timeout: 'Ovo traje predugo. Pokušaj ponovo.',
  error_server: 'Nešto je pošlo po zlu kod nas. Pokušaj ponovo.',
  session_expired: 'Tvoja sesija je istekla. Potvrdi saglasnost ponovo da nastaviš.',
  error_rate_limited: 'Previše pitanja u kratkom vremenu. Sačekaj malo i pokušaj ponovo.',
  consent_text_changed: 'Tekst saglasnosti se promijenio. Pročitaj novi tekst i potvrdi ponovo.',
  retry: 'Pokušaj ponovo',
  cancel: 'Odustani',
  dismiss: 'U redu',

  ask_placeholder: 'Upiši svoje pitanje…',
  send: 'Pošalji',
  mic_start: 'Pritisni i govori',
  mic_stop: 'Pritisni da zaustaviš',
  recording_label: 'Snimam… pritisni ponovo da zaustaviš.',
  mic_unsupported: 'Glas nije dostupan u ovom pregledaču. Možeš upisati pitanje.',
  mic_denied: 'Pristup mikrofonu je blokiran. Možeš upisati pitanje.',
  mic_error: 'Mikrofon nije radio. Možeš upisati pitanje.',
  transcribing: 'Pretvaram tvoj glas u tekst…',
  thinking: 'Tražim odgovor…',
  transcript_empty: 'Nisam ništa čula. Pokušaj ponovo, bliže telefonu.',

  heard: 'Čula sam:',
  is_this_right: 'Je li ovo tačno?',
  no_try_again: 'Ne, pokušaj ponovo',
  edit: 'Ispravi',
  you_asked: 'Tvoje pitanje:',
  answer_title: 'Odgovor',

  sources: 'Izvori',
  translated_note: 'Prevedeno sa izvornog jezika.',
  demo_badge: 'Demo: izvori još nisu pregledani',
  confidence: 'Pouzdanost',
  confidence_low: 'niska',
  confidence_medium: 'srednja',
  confidence_high: 'visoka',
  playing: 'Pušta se…',
  audio_error: 'Zvuk se ne može pustiti.',

  withheld_title: 'Ovo ne znam. Evo gdje možeš dobiti pomoć.',
  emergency_title: 'Ovo može biti hitno',
  call: 'Pozovi',
  website: 'Internet stranica',
  hours: 'Radno vrijeme',
  referral_title: 'Gdje dobiti pomoć',
  unverified_contact: 'Kontakt još nije provjeren',

  citation_title: 'Izvor',
  citation_source: 'Naslov',
  citation_section: 'Dio',
  citation_version: 'Verzija',
  citation_date: 'Datum',
  citation_page: 'Strana',
  citation_status: 'Status pregleda',
  status_reviewed: 'Pregledao ljekar',
  status_public_unreviewed: 'Javno, još nije pregledano',
  status_blocked: 'Nije odobreno',
  close: 'Zatvori',

  language: 'Jezik',
  low_bandwidth: 'Štednja podataka',
  low_bandwidth_hint: 'Manji zvuk, bez automatskog puštanja.',
  delete_data: 'Obriši moje podatke',
  delete_confirm: 'Obrisati sve o ovoj sesiji? Ovo se ne može poništiti.',
  delete: 'Obriši',
  delete_done: 'Tvoji podaci su obrisani.',
  delete_local_only: 'Obriši samo na ovom telefonu',
  delete_error: 'Nismo uspjeli doći do servera da obrišemo tvoje podatke.',
  new_question: 'Novo pitanje',
  not_advice_long:
    'MILA daje opšte informacije i kaže ti gdje možeš dobiti pomoć. Ne postavlja dijagnozu, ne propisuje lijekove i ne tumači nalaze. Ako se osjećaš loše, javi se ljekaru.',
  open_source: 'Otvoreni kod. Bez praćenja.',

  kind_clinic: 'Ambulanta',
  kind_er: 'Hitna pomoć',
  kind_helpline: 'SOS linija',
  kind_child_protection: 'Zaštita djece',
  kind_violence: 'Pomoć kod nasilja',
  kind_mental_health: 'Mentalno zdravlje',
  kind_other: 'Služba',
};

const bs: Catalogue = {
  ...sr,
  consent_intro: 'Odaberi jezik i pročitaj (ili poslušaj) kako MILA radi.',
  mic_unsupported: 'Glas nije dostupan u ovom pregledniku. Možeš upisati pitanje.',
  translated_note: 'Prevedeno s izvornog jezika.',
  not_advice_long:
    'MILA daje opće informacije i kaže ti gdje možeš dobiti pomoć. Ne postavlja dijagnozu, ne propisuje lijekove i ne tumači nalaze. Ako se osjećaš loše, javi se ljekaru.',
  error_rate_limited: 'Previše pitanja u kratkom vremenu. Pričekaj malo i pokušaj ponovo.',
};

const me: Catalogue = {
  ...sr,
  consent_intro: 'Izaberi jezik i pročitaj (ili poslušaj) kako MILA radi.',
};

const hr: Catalogue = {
  app_name: 'MILA',
  tagline: 'Pitaj o menstruaciji, trudnoći, kontracepciji i svom tijelu. Privatno i besplatno.',
  banner_not_advice: 'Samo informacije, ne medicinski savjet. U hitnom slučaju nazovi hitnu pomoć.',
  skip_to_content: 'Preskoči na sadržaj',

  consent_title: 'Prije nego počnemo',
  consent_intro: 'Odaberi jezik i pročitaj (ili poslušaj) kako MILA radi.',
  consent_language: 'Jezik',
  consent_minor_q: 'Imaš li manje od 18 godina?',
  yes: 'Da',
  no: 'Ne',
  consent_region: 'Gdje se nalaziš?',
  region_BA: 'Bosna i Hercegovina',
  region_ME: 'Crna Gora',
  listen: 'Poslušaj',
  stop: 'Zaustavi',
  consent_save_questions: 'Spremi moja pitanja',
  consent_save_hint: 'Isključeno je dok ti ne uključiš. Možeš ih izbrisati kad god želiš.',
  consent_agree: 'Slažem se',
  consent_need_minor: 'Prvo mi reci imaš li manje od 18 godina.',

  loading: 'Učitavanje…',
  error_network: 'Nema veze. Provjeri internet i pokušaj ponovno.',
  error_timeout: 'Ovo traje predugo. Pokušaj ponovno.',
  error_server: 'Nešto je pošlo po zlu kod nas. Pokušaj ponovno.',
  session_expired: 'Tvoja sesija je istekla. Potvrdi pristanak ponovno da nastaviš.',
  error_rate_limited: 'Previše pitanja u kratkom vremenu. Pričekaj malo i pokušaj ponovno.',
  consent_text_changed: 'Tekst pristanka se promijenio. Pročitaj novi tekst i potvrdi ponovno.',
  retry: 'Pokušaj ponovno',
  cancel: 'Odustani',
  dismiss: 'U redu',

  ask_placeholder: 'Upiši svoje pitanje…',
  send: 'Pošalji',
  mic_start: 'Pritisni i govori',
  mic_stop: 'Pritisni da zaustaviš',
  recording_label: 'Snimam… pritisni ponovno da zaustaviš.',
  mic_unsupported: 'Glas nije dostupan u ovom pregledniku. Možeš upisati pitanje.',
  mic_denied: 'Pristup mikrofonu je blokiran. Možeš upisati pitanje.',
  mic_error: 'Mikrofon nije radio. Možeš upisati pitanje.',
  transcribing: 'Pretvaram tvoj glas u tekst…',
  thinking: 'Tražim odgovor…',
  transcript_empty: 'Nisam ništa čula. Pokušaj ponovno, bliže telefonu.',

  heard: 'Čula sam:',
  is_this_right: 'Je li ovo točno?',
  no_try_again: 'Ne, pokušaj ponovno',
  edit: 'Ispravi',
  you_asked: 'Tvoje pitanje:',
  answer_title: 'Odgovor',

  sources: 'Izvori',
  translated_note: 'Prevedeno s izvornog jezika.',
  demo_badge: 'Demo: izvori još nisu pregledani',
  confidence: 'Pouzdanost',
  confidence_low: 'niska',
  confidence_medium: 'srednja',
  confidence_high: 'visoka',
  playing: 'Reproducira se…',
  audio_error: 'Zvuk se ne može reproducirati.',

  withheld_title: 'Ovo ne znam. Evo gdje možeš dobiti pomoć.',
  emergency_title: 'Ovo može biti hitno',
  call: 'Nazovi',
  website: 'Internetska stranica',
  hours: 'Radno vrijeme',
  referral_title: 'Gdje dobiti pomoć',
  unverified_contact: 'Kontakt još nije provjeren',

  citation_title: 'Izvor',
  citation_source: 'Naslov',
  citation_section: 'Odjeljak',
  citation_version: 'Verzija',
  citation_date: 'Datum',
  citation_page: 'Stranica',
  citation_status: 'Status pregleda',
  status_reviewed: 'Pregledao liječnik',
  status_public_unreviewed: 'Javno, još nije pregledano',
  status_blocked: 'Nije odobreno',
  close: 'Zatvori',

  language: 'Jezik',
  low_bandwidth: 'Štednja podataka',
  low_bandwidth_hint: 'Manji zvuk, bez automatske reprodukcije.',
  delete_data: 'Izbriši moje podatke',
  delete_confirm: 'Izbrisati sve o ovoj sesiji? Ovo se ne može poništiti.',
  delete: 'Izbriši',
  delete_done: 'Tvoji podaci su izbrisani.',
  delete_local_only: 'Izbriši samo na ovom telefonu',
  delete_error: 'Nismo uspjeli doći do poslužitelja da izbrišemo tvoje podatke.',
  new_question: 'Novo pitanje',
  not_advice_long:
    'MILA daje opće informacije i kaže ti gdje možeš dobiti pomoć. Ne postavlja dijagnozu, ne propisuje lijekove i ne tumači nalaze. Ako se osjećaš loše, javi se liječniku.',
  open_source: 'Otvoreni kod. Bez praćenja.',

  kind_clinic: 'Ambulanta',
  kind_er: 'Hitna pomoć',
  kind_helpline: 'SOS linija',
  kind_child_protection: 'Zaštita djece',
  kind_violence: 'Pomoć kod nasilja',
  kind_mental_health: 'Mentalno zdravlje',
  kind_other: 'Služba',
};

export const MESSAGES: Readonly<Record<Lang, Catalogue>> = { en, sr, bs, me, hr };

/** Translate a key for a locale; Cyrillic is applied for BCMS languages. */
export function t(key: MsgKey, locale: Locale): string {
  const table = MESSAGES[locale.lang] ?? MESSAGES.sr;
  const text = table[key] ?? en[key];
  return render(text, locale.lang, locale.script);
}

/** Build a bound translator for a component. */
export function translator(locale: Locale): (key: MsgKey) => string {
  return (key) => t(key, locale);
}

// --- small helpers used by several components -----------------------------------------------

/** Thresholds are a UI choice: the gate's minimum confidence is 0.35, so anything approved
 *  but below 0.5 reads as "low"; 0.5-0.75 "medium"; above 0.75 "high". */
export function confidenceKey(score: number): 'confidence_low' | 'confidence_medium' | 'confidence_high' {
  if (!Number.isFinite(score) || score < 0.5) return 'confidence_low';
  if (score < 0.75) return 'confidence_medium';
  return 'confidence_high';
}

export function reviewStatusKey(status: string): 'status_reviewed' | 'status_public_unreviewed' | 'status_blocked' {
  if (status === 'reviewed') return 'status_reviewed';
  if (status === 'blocked') return 'status_blocked';
  return 'status_public_unreviewed';
}

const KIND_KEYS: Readonly<Record<string, MsgKey>> = {
  clinic: 'kind_clinic',
  er: 'kind_er',
  helpline: 'kind_helpline',
  child_protection: 'kind_child_protection',
  violence: 'kind_violence',
  mental_health: 'kind_mental_health',
};

export function referralKindKey(kind: string): MsgKey {
  return KIND_KEYS[kind] ?? 'kind_other';
}
