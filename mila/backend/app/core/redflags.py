"""Red-flag router: rules first, character n-gram Naive Bayes second.

``RedFlagRouter.check`` runs before retrieval on every request. It never diagnoses; it only
decides whether the input describes one of ``RED_FLAG_CATEGORIES`` so that the pipeline can
answer with a referral instead of generated text.

* Rules (section "rules") are combinations of term lists from ``app.core.redflag_rules``,
  matched on ``normalize_text`` output with typo tolerance (``TermMatcher``). Rules always win
  over the classifier and ``RedFlagResult.source == "rule"``.
* The classifier (``CharNgramNaiveBayes``) is a pure-Python multinomial Naive Bayes over
  character 3-5-grams, trained at import time from the seeds in ``redflag_rules``. It fires only
  when its posterior clears the threshold with a clear margin; ``source == "classifier"``.

``RedFlagResult.matched`` only ever contains rule ids and vocabulary entries, never user text.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.config import get_settings
from app.core import redflag_rules as rules
from app.core.i18n import normalize_text
from app.core.types import RED_FLAG_CATEGORIES, RedFlagResult

NONE_LABEL = "none"

# ---------------------------------------------------------------------------------------------
# Fuzzy term matching
# ---------------------------------------------------------------------------------------------


def edit_budget(length: int) -> int:
    """Edits tolerated for a word of ``length`` characters: 0 below 5, 1 from 5, 2 from 9."""
    if length >= 9:
        return 2
    if length >= 5:
        return 1
    return 0


def levenshtein(a: str, b: str, cutoff: int) -> int:
    """Edit distance, returning ``cutoff + 1`` as soon as the distance is known to exceed it."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            current.append(value)
            if value < row_min:
                row_min = value
        if row_min > cutoff:
            return cutoff + 1
        previous = current
    return previous[-1]


def _word_matches_uncached(pattern: str, prefix: bool, exact: bool, token: str, joined: bool) -> bool:
    if token == pattern:
        return True
    if prefix and token.startswith(pattern):
        return True
    if exact or token in rules.FUZZY_EXACT_ONLY_TOKENS:
        return False
    if joined:
        # A phrase glued into one token ("nemrda" for "ne mrda") must match exactly: with edits
        # allowed, "temperaturaje" would pass for "temperatura" + "je" and "prekida" for "preti da".
        return False
    if prefix:
        budget = edit_budget(len(pattern))
        if not budget or len(token) < len(pattern) - budget:
            return False
        last = pattern[-1]
        for length in range(max(1, len(pattern) - budget), min(len(token), len(pattern) + budget) + 1):
            candidate = token[:length]
            if candidate[-1] == last and levenshtein(pattern, candidate, budget) <= budget:
                return True
        return False
    budget = edit_budget(max(len(pattern), len(token)))
    if not budget or min(len(pattern), len(token)) < 4 or abs(len(pattern) - len(token)) > budget:
        return False
    return levenshtein(pattern, token, budget) <= budget


Memo = dict[tuple[str, bool, bool, bool, str], bool]


def _word_matches(
    pattern: str, prefix: bool, exact: bool, token: str, memo: Memo, joined: bool = False
) -> bool:
    key = (pattern, prefix, exact, joined, token)
    hit = memo.get(key)
    if hit is None:
        hit = _word_matches_uncached(pattern, prefix, exact, token, joined)
        memo[key] = hit
    return hit


@dataclass(frozen=True, slots=True)
class _Word:
    text: str
    prefix: bool


@dataclass(frozen=True, slots=True)
class _Term:
    raw: str
    words: tuple[_Word, ...]
    exact: bool


@dataclass(frozen=True, slots=True)
class TermHit:
    """A vocabulary entry found at tokens ``[start, end)``. ``term`` is the entry, not user text."""

    term: str
    start: int
    end: int


_Entry = tuple[_Term, int]  # (term, number of leading words covered by the index key)
_Candidate = tuple[str, bool, bool, bool, list[_Entry]]  # (key, prefix, exact, joined, entries)
_MAX_JOIN = 3  # words of a phrase that may be glued into one token ("nemrda" for "ne mrda")


def parse_term(raw: str) -> _Term:
    exact = raw.startswith("=")
    body = raw[1:] if exact else raw
    words = tuple(_Word(w.rstrip("*"), w.endswith("*")) for w in body.split())
    if not words or any(not w.text for w in words):
        raise ValueError(f"invalid term: {raw!r}")
    return _Term(raw, words, exact)


class TermMatcher:
    """A compiled term list (see ``redflag_rules`` for the syntax) that finds hits in a token list.

    Terms are indexed by their first word (and by the first two or three words glued together,
    for inputs that lost a space), bucketed by length so that only plausible candidates reach the
    edit-distance check.
    """

    def __init__(self, terms: Iterable[str]) -> None:
        self.terms = tuple(parse_term(t) for t in terms)
        self._exact: dict[str, list[_Entry]] = {}
        self._exact_prefix: list[tuple[str, list[_Entry]]] = []
        self._plain_by_len: dict[int, list[tuple[str, bool, list[_Entry]]]] = {}
        self._prefix_by_len: dict[int, list[tuple[str, list[_Entry]]]] = {}
        keyed: dict[tuple[str, bool, bool, bool], list[_Entry]] = {}
        for term in self.terms:
            for k in range(1, min(_MAX_JOIN, len(term.words)) + 1):
                head = term.words[:k]
                if any(w.prefix for w in head[:-1]):
                    break
                key = ("".join(w.text for w in head), head[-1].prefix, term.exact, k > 1)
                keyed.setdefault(key, []).append((term, k))
        for (text, prefix, exact, joined), entries in keyed.items():
            if exact and not prefix:
                self._exact.setdefault(text, []).extend(entries)
            elif exact:
                self._exact_prefix.append((text, entries))
            elif prefix and not joined:
                self._prefix_by_len.setdefault(len(text), []).append((text, entries))
            else:
                self._plain_by_len.setdefault(len(text), []).append((text, joined, entries))
        self._max_prefix_len = max(self._prefix_by_len, default=0)

    def _candidates(self, token: str) -> Iterable[_Candidate]:
        entries = self._exact.get(token)
        if entries:
            yield token, False, True, False, entries
        for text, exact_entries in self._exact_prefix:
            if token.startswith(text):
                yield text, True, True, False, exact_entries
        length = len(token)
        for candidate_len in range(length - 2, length + 3):
            for text, joined, plain_entries in self._plain_by_len.get(candidate_len, ()):
                yield text, False, False, joined, plain_entries
        for candidate_len in range(1, min(self._max_prefix_len, length + 2) + 1):
            for text, prefix_entries in self._prefix_by_len.get(candidate_len, ()):
                yield text, True, False, False, prefix_entries

    def _match_from(self, term: _Term, wi: int, tokens: Sequence[str], ti: int, memo: Memo) -> int | None:
        words = term.words
        if wi == len(words):
            return ti
        if ti >= len(tokens):
            return None
        token = tokens[ti]
        for k in range(1, min(_MAX_JOIN, len(words) - wi) + 1):
            segment = words[wi : wi + k]
            if any(w.prefix for w in segment[:-1]):
                break
            joined = "".join(w.text for w in segment)
            if _word_matches(joined, segment[-1].prefix, term.exact, token, memo, joined=k > 1):
                end = self._match_from(term, wi + k, tokens, ti + 1, memo)
                if end is not None:
                    return end
        return None

    def find_all(self, tokens: Sequence[str], memo: Memo) -> list[TermHit]:
        found: set[TermHit] = set()
        for i, token in enumerate(tokens):
            for text, prefix, exact, joined, entries in self._candidates(token):
                if not _word_matches(text, prefix, exact, token, memo, joined=joined):
                    continue
                for term, k in entries:
                    end = self._match_from(term, k, tokens, i + 1, memo)
                    if end is not None:
                        found.add(TermHit(term.raw, i, end))
        return sorted(found, key=lambda h: (h.start, -h.end, h.term))


# ---------------------------------------------------------------------------------------------
# Per-request analysis helpers
# ---------------------------------------------------------------------------------------------


def _compile(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


def _blank_match(match: re.Match[str]) -> str:
    """Replace a matched span by placeholder tokens so that token positions stay aligned."""
    span = match.group(0)
    lead = len(span) - len(span.lstrip(" "))
    trail = len(span) - len(span.rstrip(" "))
    inner = span.strip(" ")
    return " " * lead + " ".join("_" for _ in inner.split()) + " " * trail


def blank(text: str, patterns: Iterable[re.Pattern[str]]) -> str:
    for pattern in patterns:
        text = pattern.sub(_blank_match, text)
    return text


class _Text:
    """One (possibly blanked) token view of the input with memoised matcher results."""

    def __init__(self, text: str, memo: Memo) -> None:
        self.text = text
        self.tokens = text.split()
        self._memo = memo
        self._hits: dict[int, list[TermHit]] = {}

    def hits(self, matcher: TermMatcher) -> list[TermHit]:
        key = id(matcher)
        found = self._hits.get(key)
        if found is None:
            found = matcher.find_all(self.tokens, self._memo)
            self._hits[key] = found
        return found

    def first(self, matcher: TermMatcher) -> TermHit | None:
        found = self.hits(matcher)
        return found[0] if found else None

    def has(self, matcher: TermMatcher) -> bool:
        return bool(self.hits(matcher))


def _gap(a: TermHit, b: TermHit) -> int:
    """Tokens strictly between two hits (negative when they overlap)."""
    return max(a.start, b.start) - min(a.end, b.end)


def _near(a: TermHit, b: TermHit, window: int) -> bool:
    return _gap(a, b) <= window


def _any_near(
    first: Iterable[TermHit], second: Sequence[TermHit], window: int
) -> tuple[TermHit, TermHit] | None:
    for a in first:
        for b in second:
            if _near(a, b, window):
                return a, b
    return None


def _first_age(patterns: Iterable[re.Pattern[str]], text: str) -> int | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


class _Matchers:
    """All compiled term lists; built once at import."""

    def __init__(self) -> None:
        r = rules
        self.pregnancy = TermMatcher(r.PREGNANCY_CTX)
        self.postpartum = TermMatcher(r.POSTPARTUM_CTX)
        self.baby = TermMatcher(r.BABY_TERMS)
        self.menstrual = TermMatcher(r.MENSTRUAL_CTX)
        self.non_gyn = TermMatcher(r.NON_GYN_BLEEDING_CTX)
        self.vaginal = TermMatcher(r.VAGINAL_BLEEDING_CUES)
        self.bleeding = TermMatcher(r.BLEEDING)
        self.bleeding_first_person = TermMatcher(r.BLEEDING_FIRST_PERSON)
        self.soaking = TermMatcher(r.SOAKING_QUALIFIERS)
        self.heavy = TermMatcher(r.HEAVY_QUALIFIERS)
        self.fever = TermMatcher(r.FEVER_TERMS)
        self.temperature_mention = TermMatcher(r.TEMPERATURE_MENTION_TERMS)
        self.headache = TermMatcher(r.HEADACHE_TERMS)
        self.severe_headache = TermMatcher(r.SEVERE_HEADACHE_PHRASES)
        self.persistent = TermMatcher(r.PERSISTENT_QUALIFIERS)
        self.vision = TermMatcher(r.VISION_TERMS)
        self.swelling = TermMatcher(r.SWELLING_TERMS)
        self.face_hands = TermMatcher(r.FACE_HANDS_TERMS)
        self.sudden_swelling = TermMatcher(r.SUDDEN_SWELLING_PHRASES)
        self.not_moving = TermMatcher(r.NOT_MOVING_TERMS)
        self.movement_nouns = TermMatcher(r.MOVEMENT_NOUNS)
        self.reduction = TermMatcher(r.REDUCTION_WORDS)
        self.non_fetal_movement = TermMatcher(r.NON_FETAL_MOVEMENT_CTX)
        self.abdomen = TermMatcher(r.ABDOMEN_TERMS)
        self.pain = TermMatcher(r.PAIN_TERMS)
        self.tier1 = TermMatcher(r.SEVERE_TIER1)
        self.tier2 = TermMatcher(r.SEVERE_TIER2)
        self.functional = TermMatcher(r.FUNCTIONAL_IMPACT_TERMS)
        self.contraction = TermMatcher(r.CONTRACTION_TERMS)
        self.contraction_qualifier = TermMatcher(r.CONTRACTION_QUALIFIERS)
        self.suicide = TermMatcher(r.SUICIDE_TERMS)
        self.violence = TermMatcher(r.VIOLENCE_TERMS)
        self.minor = TermMatcher(r.MINOR_TERMS)
        self.adult_partner = TermMatcher(r.ADULT_PARTNER_TERMS)
        self.adult_generic = TermMatcher(r.ADULT_GENERIC_TERMS)
        self.authority = TermMatcher(r.ADULT_AUTHORITY_TERMS)
        self.explicit = TermMatcher(r.SEXUAL_EXPLICIT_TERMS)
        self.relationship = TermMatcher(r.RELATIONSHIP_TERMS)
        self.framing = TermMatcher(r.PREGNANCY_FRAMING_TERMS)
        self.contact = TermMatcher(r.SEXUAL_CONTACT_BY_OTHER_TERMS)


def expand_number_words(normalised: str) -> str:
    """Rewrite spelled-out numbers as digits ("dvadeset osam" -> "28", "fifteen" -> "15").

    Runs on normalised text before the age and temperature regexes, so "imam petnaest godina a
    decko ima dvadeset osam" and "trideset osam i po" are seen as numbers. Units after a tens word
    are merged; a lone unit word ("jedan", "one") stays a word because it is rarely an age.
    """
    tokens = normalised.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in rules.NUMBER_WORD_TENS:
            value = rules.NUMBER_WORD_TENS[tok]
            if i + 1 < len(tokens) and tokens[i + 1] in rules.NUMBER_WORD_UNITS:
                value += rules.NUMBER_WORD_UNITS[tokens[i + 1]]
                i += 1
            out.append(str(value))
        elif tok in rules.NUMBER_WORD_TEENS:
            out.append(str(rules.NUMBER_WORD_TEENS[tok]))
        else:
            out.append(tok)
        i += 1
    return " ".join(out)


class _Patterns:
    def __init__(self) -> None:
        self.pregnancy_weeks = re.compile(rules.PREGNANCY_WEEKS_RE)
        self.information_frame = _compile(rules.INFORMATION_FRAME_PATTERNS)
        self.first_person_symptom = re.compile(rules.FIRST_PERSON_SYMPTOM_RE)
        self.contraction_interval = re.compile(rules.CONTRACTION_INTERVAL_RE)
        r = rules
        self.hypothetical_pregnancy = _compile(r.HYPOTHETICAL_PREGNANCY_PATTERNS)
        self.bleeding_exclusion = _compile(r.BLEEDING_EXCLUSION_PATTERNS)
        self.fever_exclusion = _compile(r.BABY_FEVER_PATTERNS + r.FEVER_EXCLUSION_PATTERNS)
        self.suicide_exclusion = _compile(r.SUICIDE_EXCLUSION_PATTERNS)
        self.violence_exclusion = _compile(r.VIOLENCE_EXCLUSION_PATTERNS)
        self.adult_exclusion = _compile(r.ADULT_EXCLUSION_PATTERNS)
        self.minor_age = _compile(r.MINOR_AGE_PATTERNS)
        self.self_adult_age = _compile(r.SELF_ADULT_AGE_PATTERNS)
        self.adult_age = _compile(r.ADULT_AGE_PATTERNS)
        self.temperature_number = re.compile(r.TEMPERATURE_NUMBER_RE)
        self.low_temperature_number = re.compile(r.LOW_TEMPERATURE_NUMBER_RE)
        self.temperature_cue = re.compile(r.TEMPERATURE_CUE_RE)
        self.gestation_weeks = re.compile(r.GESTATION_WEEKS_RE)


M = _Matchers()
P = _Patterns()


class _Analysis:
    """Everything the rules need to know about one input, computed lazily and cached."""

    def __init__(self, normalised: str, is_minor: bool | None) -> None:
        self.is_minor = is_minor
        self._memo: Memo = {}
        self.base = _Text(normalised, self._memo)
        self._views: dict[str, _Text] = {}
        # Categories a rule looked at closely and rejected (e.g. temperature below 38, no adult
        # age gap). Rules win over the classifier in both directions, so these are never fired
        # by the classifier.
        self.vetoes: set[str] = set()

    def view(self, name: str, patterns: Iterable[re.Pattern[str]]) -> _Text:
        """The input with ``patterns`` blanked out (token positions preserved)."""
        text = self._views.get(name)
        if text is None:
            text = _Text(blank(self.base.text, patterns), self._memo)
            self._views[name] = text
        return text

    def pregnancy(self) -> TermHit | None:
        hit = self.view("pregnancy", P.hypothetical_pregnancy).first(M.pregnancy)
        if hit:
            return hit
        match = P.pregnancy_weeks.search(self.base.text)
        if match:
            start = len(self.base.text[: match.start()].split())
            end = start + max(1, len(match.group(0).split()))
            return TermHit("gestation_weeks", start, end)
        return None

    @property
    def information_question(self) -> bool:
        """An information question about danger signs with no present, first-person symptom.

        Such a question is answered from the knowledge base (the danger-signs documents); the
        obstetric rules are skipped. A message that also reports a symptom ("koji su znaci
        preeklampsije, imam jaku glavobolju") is still routed.
        """
        text = self.base.text
        if not any(rx.search(text) for rx in P.information_frame):
            return False
        return P.first_person_symptom.search(text) is None

    def pregnancy_or_postpartum(self) -> TermHit | None:
        return self.pregnancy() or self.base.first(M.postpartum)


# ---------------------------------------------------------------------------------------------
# Rules (each returns a label built from rule ids and vocabulary entries, or None)
# ---------------------------------------------------------------------------------------------

_NEAR_HEAVY = 6  # tokens between a bleeding term and a heaviness qualifier
_NEAR_NON_GYN = 2  # tokens between a bleeding term and "nos" / "desni" / "stolica"
_NEAR_SEVERITY = 5  # tokens between a pain / headache term and its qualifier
_NEAR_PAIN_SITE = 8  # tokens between a pain term and an abdomen term
_NEAR_SWELLING = 4  # tokens between "otekle" and "ruke" / "lice"
_NEAR_REDUCTION = 3  # tokens between "pokreti" and "slabiji"
_ADULT_GAP_YEARS = 3  # minimum stated age gap for a partner to count as an adult
_ADULT_ALONE_YEARS = 21  # partner age that counts as adult whatever the minor's stated age
_ADULT_WITH_FLAG_YEARS = 20  # partner age that counts as adult when only is_minor is known


def _negated(text: _Text, hit: TermHit) -> bool:
    return hit.start > 0 and text.tokens[hit.start - 1] in rules.NEGATION_TOKENS


def _rule_bleeding_pregnancy(a: _Analysis) -> str | None:
    text = a.view("bleeding", P.bleeding_exclusion)
    if not text.has(M.bleeding):
        return None
    a.vetoes.add("bleeding_pregnancy")  # cleared below when the combination holds
    bleeds = [h for h in text.hits(M.bleeding) if not _negated(text, h)]
    if not text.has(M.vaginal):
        non_gyn = text.hits(M.non_gyn)
        bleeds = [h for h in bleeds if not any(_near(h, n, _NEAR_NON_GYN) for n in non_gyn)]
    if not bleeds:
        return None
    pregnancy = a.pregnancy()
    postpartum = a.base.first(M.postpartum)
    heavy = _any_near(bleeds, text.hits(M.heavy), _NEAR_HEAVY)
    label: str | None = None
    if pregnancy:
        label = f"{bleeds[0].term}+{pregnancy.term}"
    elif a.base.has(M.menstrual) and not postpartum:
        soaking = _any_near(bleeds, text.hits(M.soaking), _NEAR_HEAVY)
        label = f"{soaking[0].term}+{soaking[1].term}+menstrual" if soaking else None
    elif postpartum:
        first_person = text.first(M.bleeding_first_person)
        if first_person:
            label = f"{first_person.term}+{postpartum.term}"
        elif heavy:
            label = f"{heavy[0].term}+{heavy[1].term}+{postpartum.term}"
    elif heavy:
        label = f"{heavy[0].term}+{heavy[1].term}"
    if label:
        a.vetoes.discard("bleeding_pregnancy")
    return label


def _rule_fever_pregnancy(a: _Analysis) -> str | None:
    context = a.pregnancy_or_postpartum()
    if not context:
        return None
    text = a.view("fever", P.fever_exclusion)
    strong = text.first(M.fever)
    if strong:
        return f"{strong.term}+{context.term}"
    if P.temperature_number.search(text.text) and P.temperature_cue.search(text.text):
        return f"temperature>=38+{context.term}"
    mention = text.first(M.temperature_mention)
    if mention and not P.low_temperature_number.search(text.text):
        return f"{mention.term}+{context.term}"
    if mention:
        a.vetoes.add("fever_pregnancy")  # a stated temperature below 38 is not a fever
    return None


def _rule_preeclampsia(a: _Analysis) -> str | None:
    context = a.pregnancy_or_postpartum()
    if not context:
        return None
    text = a.base
    severe = text.first(M.severe_headache)
    if severe:
        return f"{severe.term}+{context.term}"
    heads = text.hits(M.headache)
    if heads:
        qualifiers = text.hits(M.tier1) + text.hits(M.tier2) + text.hits(M.persistent)
        pair = _any_near(heads, qualifiers, _NEAR_SEVERITY)
        if pair:
            return f"{pair[0].term}+{pair[1].term}+{context.term}"
    vision = text.first(M.vision)
    if vision:
        return f"{vision.term}+{context.term}"
    sudden = text.first(M.sudden_swelling)
    if sudden:
        return f"{sudden.term}+{context.term}"
    pair = _any_near(text.hits(M.swelling), text.hits(M.face_hands), _NEAR_SWELLING)
    if pair:
        return f"{pair[0].term}+{pair[1].term}+{context.term}"
    return None


_MOVEMENT_WORDS = ("pokret", "movement", "kick", "sutir")


def _fetal_subject(a: _Analysis) -> str | None:
    """What the movement wording is about: a baby word, a pregnancy context or a gestational age."""
    baby = a.base.first(M.baby)
    if baby:
        return baby.term
    pregnancy = a.pregnancy()
    if pregnancy:
        return pregnancy.term
    if P.gestation_weeks.search(a.base.text):
        return "gestation_weeks"
    return None


def _rule_reduced_fetal_movement(a: _Analysis) -> str | None:
    text = a.base
    if text.has(M.non_fetal_movement):
        return None
    subject = _fetal_subject(a)
    not_moving = text.first(M.not_moving)
    if not_moving and (subject or any(w in not_moving.term for w in _MOVEMENT_WORDS)):
        return f"{subject or 'movements'}+{not_moving.term}"
    pair = _any_near(text.hits(M.movement_nouns), text.hits(M.reduction), _NEAR_REDUCTION)
    if pair:
        return f"{subject or 'movements'}+{pair[0].term}+{pair[1].term}"
    return None


def _rule_severe_abdominal_pain(a: _Analysis) -> str | None:
    text = a.base
    pregnancy = a.pregnancy_or_postpartum()
    if pregnancy:
        contraction = text.first(M.contraction)
        if contraction:
            if P.contraction_interval.search(text.text):
                return f"{contraction.term}+interval+{pregnancy.term}"
            qualifier = text.first(M.contraction_qualifier)
            if qualifier and _near(qualifier, contraction, _NEAR_SEVERITY):
                return f"{contraction.term}+{qualifier.term}+{pregnancy.term}"
        functional = text.first(M.functional)
        if functional and text.has(M.abdomen):
            return f"{functional.term}+abdomen+{pregnancy.term}"
    sites = text.hits(M.abdomen)
    if not sites:
        return None
    period_only = text.has(M.menstrual) and not a.pregnancy()
    qualifiers = list(text.hits(M.tier2))
    if not period_only:
        qualifiers += text.hits(M.tier1)
    for pain in text.hits(M.pain):
        site = next((s for s in sites if _near(pain, s, _NEAR_PAIN_SITE)), None)
        if site is None:
            continue
        for qualifier in qualifiers:
            if _near(qualifier, pain, _NEAR_SEVERITY) or _near(qualifier, site, _NEAR_SEVERITY):
                return f"{qualifier.term}+{pain.term}+{site.term}"
    pair = _any_near(text.hits(M.functional), sites, _NEAR_PAIN_SITE)
    if pair:
        return f"{pair[0].term}+{pair[1].term}"
    return None


def _rule_suicidal_ideation(a: _Analysis) -> str | None:
    hit = a.view("suicide", P.suicide_exclusion).first(M.suicide)
    return hit.term if hit else None


def _rule_violence_coercion(a: _Analysis) -> str | None:
    hit = a.view("violence", P.violence_exclusion).first(M.violence)
    return hit.term if hit else None


def _rule_minor_sexual_adult(a: _Analysis) -> str | None:
    text = a.view("adult", P.adult_exclusion)
    minor_age = _first_age(P.minor_age, text.text)
    minor_term = text.first(M.minor)
    if minor_age is not None:
        minor = f"age={minor_age}"
    elif minor_term:
        minor = minor_term.term
    elif a.is_minor is True and _first_age(P.self_adult_age, text.text) is None:
        minor = "is_minor"
    else:
        return None
    a.vetoes.add("minor_sexual_adult")  # a minor asking an ordinary question is not a flag
    contact = text.first(M.contact)
    if contact:
        return f"{minor}+{contact.term}"
    explicit = text.first(M.explicit)
    relationship = text.first(M.relationship)
    framing = text.first(M.framing)
    adult_age = _first_age(P.adult_age, text.text)
    adult_by_age = adult_age is not None and (
        (minor_age is None and adult_age >= _ADULT_WITH_FLAG_YEARS)
        or (
            minor_age is not None
            and (adult_age - minor_age >= _ADULT_GAP_YEARS or adult_age >= _ADULT_ALONE_YEARS)
        )
    )
    partner = text.first(M.adult_partner)
    sexual = explicit or relationship
    if adult_by_age and (sexual or framing):
        return f"{minor}+adult_age={adult_age}+{(sexual or framing).term}"
    if partner and (sexual or framing):
        return f"{minor}+{partner.term}+{(sexual or framing).term}"
    other = text.first(M.authority) or text.first(M.adult_generic)
    if other and sexual:
        return f"{minor}+{other.term}+{sexual.term}"
    return None


OBSTETRIC_CATEGORIES: frozenset[str] = frozenset(
    {"bleeding_pregnancy", "fever_pregnancy", "preeclampsia", "reduced_fetal_movement", "severe_abdominal_pain"}
)

_RULES: dict[str, Callable[[_Analysis], str | None]] = {
    "minor_sexual_adult": _rule_minor_sexual_adult,
    "suicidal_ideation": _rule_suicidal_ideation,
    "violence_coercion": _rule_violence_coercion,
    "bleeding_pregnancy": _rule_bleeding_pregnancy,
    "preeclampsia": _rule_preeclampsia,
    "reduced_fetal_movement": _rule_reduced_fetal_movement,
    "fever_pregnancy": _rule_fever_pregnancy,
    "severe_abdominal_pain": _rule_severe_abdominal_pain,
}
assert set(_RULES) == set(RED_FLAG_CATEGORIES) == set(rules.RULE_ORDER)

# The classifier may only propose a category whose defining context the rules also require: a
# pregnancy for the obstetric categories, a baby for fetal movement, an abdomen term for pain.
# ``minor_sexual_adult`` is rule-only, because "minor" is a fact about the user (age or
# ``is_minor``), not a vocabulary distribution.
_CLASSIFIER_GATES: dict[str, Callable[[_Analysis], bool]] = {
    "bleeding_pregnancy": lambda a: a.base.has(M.bleeding),
    "fever_pregnancy": lambda a: a.pregnancy_or_postpartum() is not None,
    "preeclampsia": lambda a: a.pregnancy_or_postpartum() is not None,
    "reduced_fetal_movement": lambda a: _fetal_subject(a) is not None or a.base.has(M.movement_nouns),
    "severe_abdominal_pain": lambda a: a.base.has(M.abdomen),
    "suicidal_ideation": lambda a: True,
    "violence_coercion": lambda a: True,
    "minor_sexual_adult": lambda a: False,
}
_CLASSIFIER_MIN_TOKENS = 5  # shorter inputs carry too few n-grams for a trustworthy posterior


# ---------------------------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------------------------


def char_ngrams(text: str, low: int = 3, high: int = 5) -> Counter[str]:
    """Counts of character n-grams (``low``..``high``) of the padded, normalised text."""
    padded = f" {text} "
    grams: Counter[str] = Counter()
    for n in range(low, high + 1):
        for i in range(len(padded) - n + 1):
            grams[padded[i : i + n]] += 1
    return grams


class CharNgramNaiveBayes:
    """Multinomial Naive Bayes over character n-grams, with additive smoothing. Pure Python.

    ``alpha`` is deliberately large (3.0): with ~25 seeds per category against ~170 benign
    seeds, a small alpha lets the sparse positive classes win on any shared vocabulary
    ("pokreti bebe"), while 3.0 keeps every benign eval text in the ``none`` class with a wide
    margin and still recognises paraphrases the rules miss.
    """

    def __init__(self, alpha: float = 3.0, low: int = 3, high: int = 5) -> None:
        self.alpha = alpha
        self.low = low
        self.high = high
        self.labels: tuple[str, ...] = ()
        self._log_prior: dict[str, float] = {}
        self._log_prob: dict[str, dict[str, float]] = {}
        self._log_unseen: dict[str, float] = {}
        self._vocabulary: set[str] = set()

    def fit(self, texts_by_label: dict[str, Sequence[str]]) -> CharNgramNaiveBayes:
        counts: dict[str, Counter[str]] = {}
        docs: dict[str, int] = {}
        for label, texts in texts_by_label.items():
            total: Counter[str] = Counter()
            for text in texts:
                total.update(char_ngrams(normalize_text(text), self.low, self.high))
            counts[label] = total
            docs[label] = len(texts)
        self._vocabulary = set().union(*(c.keys() for c in counts.values()))
        vocab_size = len(self._vocabulary)
        n_docs = sum(docs.values())
        self.labels = tuple(counts)
        for label, total in counts.items():
            denominator = sum(total.values()) + self.alpha * vocab_size
            self._log_prior[label] = math.log(docs[label] / n_docs)
            self._log_prob[label] = {f: math.log((c + self.alpha) / denominator) for f, c in total.items()}
            self._log_unseen[label] = math.log(self.alpha / denominator)
        return self

    def predict_proba(self, normalised_text: str) -> dict[str, float]:
        grams = {
            f: c
            for f, c in char_ngrams(normalised_text, self.low, self.high).items()
            if f in self._vocabulary
        }
        scores: dict[str, float] = {}
        for label in self.labels:
            table = self._log_prob[label]
            unseen = self._log_unseen[label]
            scores[label] = self._log_prior[label] + sum(c * table.get(f, unseen) for f, c in grams.items())
        top = max(scores.values())
        weights = {label: math.exp(score - top) for label, score in scores.items()}
        total = sum(weights.values())
        return {label: weight / total for label, weight in weights.items()}

    def predict(self, normalised_text: str) -> tuple[str, float, float]:
        """Return ``(label, posterior, margin)`` where margin is posterior minus the runner-up."""
        proba = self.predict_proba(normalised_text)
        ranked = sorted(proba.items(), key=lambda kv: kv[1], reverse=True)
        label, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return label, best, best - second


def train_classifier() -> CharNgramNaiveBayes:
    """Train the import-time classifier from the seeds in ``redflag_rules``."""
    data: dict[str, Sequence[str]] = {label: seeds for label, seeds in rules.POSITIVE_SEEDS.items()}
    data[NONE_LABEL] = rules.NEGATIVE_SEEDS
    return CharNgramNaiveBayes().fit(data)


CLASSIFIER = train_classifier()


# ---------------------------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------------------------


class RedFlagRouter:
    """Rules first, classifier second. See the module docstring."""

    def __init__(
        self,
        classifier_threshold: float = 0.85,
        *,
        classifier_margin: float = 0.5,
        classifier: CharNgramNaiveBayes | None = None,
    ) -> None:
        self.classifier_threshold = classifier_threshold
        self.classifier_margin = classifier_margin
        self.classifier = classifier or CLASSIFIER

    def check(self, text: str, *, lang: str | None = None, is_minor: bool | None = None) -> RedFlagResult:
        """Classify one input. ``lang`` is accepted for the contract; the rules cover every language at once."""
        normalised = expand_number_words(normalize_text(text or ""))
        if not normalised:
            return RedFlagResult()
        analysis = _Analysis(normalised, is_minor)
        info_question = analysis.information_question
        for category in rules.RULE_ORDER:
            if info_question and category in OBSTETRIC_CATEGORIES:
                continue
            matched = _RULES[category](analysis)
            if matched:
                return RedFlagResult(
                    flagged=True,
                    category=category,
                    matched=f"{category}:{matched}",
                    score=1.0,
                    source="rule",
                    child_protection=category == "minor_sexual_adult",
                )
        label, posterior, margin = self.classifier.predict(normalised)
        if (
            label != NONE_LABEL
            and posterior >= self.classifier_threshold
            and margin >= self.classifier_margin
            and len(analysis.base.tokens) >= _CLASSIFIER_MIN_TOKENS
            and label not in analysis.vetoes
            and not (info_question and label in OBSTETRIC_CATEGORIES)
            and _CLASSIFIER_GATES[label](analysis)
        ):
            return RedFlagResult(
                flagged=True,
                category=label,
                matched=f"classifier:{label}",
                score=round(posterior, 4),
                source="classifier",
                child_protection=label == "minor_sexual_adult",
            )
        return RedFlagResult(score=round(posterior if label != NONE_LABEL else 0.0, 4))


_ROUTER: RedFlagRouter | None = None


def get_router() -> RedFlagRouter:
    """Module-level singleton configured from ``MILA_REDFLAG_CLASSIFIER_THRESHOLD``."""
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = RedFlagRouter(get_settings().redflag_classifier_threshold)
    return _ROUTER
