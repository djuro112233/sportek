import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  confidenceKey,
  detectLocale,
  htmlLang,
  LANGUAGE_OPTIONS,
  latinToCyrillic,
  localeFromId,
  localeId,
  MESSAGES,
  referralKindKey,
  render,
  reviewStatusKey,
  t,
} from '../lib/i18n.ts';

test('latinToCyrillic handles digraphs before single letters', () => {
  assert.equal(latinToCyrillic('ljubav'), 'љубав');
  assert.equal(latinToCyrillic('Njegoš'), 'Његош');
  assert.equal(latinToCyrillic('džem'), 'џем');
  assert.equal(latinToCyrillic('LJUBAV'), 'ЉУБАВ');
  assert.equal(latinToCyrillic('nadživjeti'), 'наџивјети');
});

test('latinToCyrillic maps every single letter and keeps case, digits and punctuation', () => {
  assert.equal(latinToCyrillic('Čćžšđ abc'), 'Чћжшђ абц');
  assert.equal(latinToCyrillic('Pitaj o trudnoći, 18 godina!'), 'Питај о трудноћи, 18 година!');
  assert.equal(latinToCyrillic('MILA'), 'МИЛА');
});

test('render applies Cyrillic only for BCMS languages', () => {
  assert.equal(render('pomoć', 'sr', 'cyrillic'), 'помоћ');
  assert.equal(render('pomoć', 'me', 'cyrillic'), 'помоћ');
  assert.equal(render('pomoć', 'sr', 'latin'), 'pomoć');
  assert.equal(render('help', 'en', 'cyrillic'), 'help');
});

test('every language has every key of the English catalogue, and no extras', () => {
  const enKeys = Object.keys(MESSAGES.en).sort();
  for (const lang of ['sr', 'bs', 'me', 'hr'] as const) {
    assert.deepEqual(Object.keys(MESSAGES[lang]).sort(), enKeys, `catalogue for ${lang}`);
    for (const key of enKeys) {
      const value = (MESSAGES[lang] as Record<string, string>)[key];
      assert.ok(typeof value === 'string' && value.trim().length > 0, `${lang}.${key} is empty`);
    }
  }
});

test('BCMS strings avoid letters with no Cyrillic equivalent so transliteration is exact', () => {
  for (const lang of ['sr', 'bs', 'me', 'hr'] as const) {
    for (const [key, value] of Object.entries(MESSAGES[lang])) {
      assert.doesNotMatch(value, /[qwxyQWXY]/, `${lang}.${key} contains q/w/x/y: ${value}`);
    }
  }
});

test('t falls back to English for unknown languages and transliterates sr-Cyrl', () => {
  assert.equal(t('yes', { lang: 'en', script: 'latin' }), 'Yes');
  assert.equal(t('yes', { lang: 'sr', script: 'latin' }), 'Da');
  assert.equal(t('yes', { lang: 'sr', script: 'cyrillic' }), 'Да');
  assert.equal(t('send', { lang: 'hr', script: 'latin' }), 'Pošalji');
  assert.equal(t('yes', { lang: 'xx' as 'en', script: 'latin' }), 'Da');
});

test('language options are unique and round-trip through localeId/localeFromId', () => {
  const ids = LANGUAGE_OPTIONS.map((o) => o.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const o of LANGUAGE_OPTIONS) {
    const locale = localeFromId(o.id);
    assert.deepEqual(locale, { lang: o.lang, script: o.script });
    assert.equal(localeId(locale), o.id);
  }
  assert.deepEqual(localeFromId('nope'), { lang: 'sr', script: 'latin' });
  assert.equal(htmlLang({ lang: 'sr', script: 'cyrillic' }), 'sr-Cyrl');
  assert.equal(htmlLang({ lang: 'me', script: 'latin' }), 'cnr');
});

test('detectLocale picks a supported language from navigator.languages', () => {
  assert.deepEqual(detectLocale(['sr-Cyrl-RS']), { lang: 'sr', script: 'cyrillic' });
  assert.deepEqual(detectLocale(['de-DE', 'hr']), { lang: 'hr', script: 'latin' });
  assert.deepEqual(detectLocale(['de-DE']), { lang: 'sr', script: 'latin' });
  assert.deepEqual(detectLocale(undefined), { lang: 'sr', script: 'latin' });
});

test('confidence, review status and referral kind map to catalogue keys', () => {
  assert.equal(confidenceKey(0.1), 'confidence_low');
  assert.equal(confidenceKey(0.6), 'confidence_medium');
  assert.equal(confidenceKey(0.9), 'confidence_high');
  assert.equal(confidenceKey(Number.NaN), 'confidence_low');
  assert.equal(reviewStatusKey('reviewed'), 'status_reviewed');
  assert.equal(reviewStatusKey('blocked'), 'status_blocked');
  assert.equal(reviewStatusKey('anything'), 'status_public_unreviewed');
  assert.equal(referralKindKey('er'), 'kind_er');
  assert.equal(referralKindKey('unknown'), 'kind_other');
});
