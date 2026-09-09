"""Structured listing extraction from a host's spoken (transcribed) description.

Two paths, same output shape:

* **LLM** (``LLM_PROVIDER`` = ollama | openai): the model returns one JSON object with the listing
  fields in *both* languages. Numbers are validated and cleaned; anything the model leaves empty is
  back-filled from the rules path.
* **Rules** (``LLM_PROVIDER=none``, the model is down, or it returns invalid JSON): deterministic regular
  expressions tuned for Montenegrin / Serbian / Croatian (Latin script, with or without diacritics) and
  English. The rules path cannot translate: it copies the local text into the ``*_en`` fields and marks
  the draft ``translation_pending=True`` so the UI and the validator can say so honestly.

Output::

    {
      "fields": {title_local, title_en, description_local, description_en, category, price_min, price_max,
                 currency, season, capacity, accessibility_local, accessibility_en, lat, lng},
      "missing_fields": [...],            # subset of REQUIRED_FIELDS still empty
      "extraction_method": "llm" | "rules",
      "translation_pending": bool,
      "llm_provider": "ollama" | "openai" | "none",
    }

Nothing in this module logs the transcript or any name. The host's display name is only used as a
last-resort title fallback ("Accommodation — <display name>"), which the host confirms before publication.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from ..providers.llm import LLMUnavailable, get_llm, parse_json_object

log = logging.getLogger(__name__)

CATEGORIES = ("accommodation", "food", "guiding", "craft", "experience", "transport", "other")
REQUIRED_FIELDS = ("title", "description", "category", "price_range", "season", "capacity", "accessibility", "coordinates")
FIELD_NAMES = (
    "title_local", "title_en", "description_local", "description_en", "category", "price_min", "price_max",
    "currency", "season", "capacity", "accessibility_local", "accessibility_en", "lat", "lng",
)
DESCRIPTION_MAX_CHARS = 600
TITLE_MAX_CHARS = 90

CATEGORY_LABELS = {
    "accommodation": ("Smještaj", "Accommodation"),
    "food": ("Hrana i piće", "Food and drink"),
    "guiding": ("Vođenje", "Guiding"),
    "craft": ("Zanat", "Craft"),
    "experience": ("Doživljaj", "Experience"),
    "transport": ("Prevoz", "Transport"),
    "other": ("Ponuda", "Offer"),
}


# ----------------------------------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------------------------------
_FOLD_MAP = str.maketrans({"đ": "d", "Đ": "D", "ß": "ss", "ł": "l", "Ł": "L"})


def ascii_fold(text: str) -> str:
    """'Donja Lastva, pješačenje, đak' → 'Donja Lastva, pjesacenje, dak'. Keeps case."""
    text = text.translate(_FOLD_MAP)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    """Lower-cased, diacritics removed, whitespace collapsed — the matching form of a transcript."""
    return " ".join(ascii_fold(text).lower().split())


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p.strip() for p in parts if p.strip()]


def _clauses(sentence: str) -> list[str]:
    parts = re.split(r"\s*[,;:]\s*|\s+[–—-]\s+|\s*\(", sentence)
    return [p.strip(" .)") for p in parts if p.strip(" .)")]


def _cap_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-–—") + "…"


# ----------------------------------------------------------------------------------------------------
# numbers (digits or small number words in both languages)
# ----------------------------------------------------------------------------------------------------
_NUMBER_WORDS = {
    "jedan": 1, "jedna": 1, "jedno": 1, "dva": 2, "dvije": 2, "dve": 2, "tri": 3, "cetiri": 4, "pet": 5,
    "sest": 6, "sedam": 7, "osam": 8, "devet": 9, "deset": 10, "jedanaest": 11, "dvanaest": 12,
    "trinaest": 13, "cetrnaest": 14, "petnaest": 15, "sesnaest": 16, "sedamnaest": 17, "osamnaest": 18,
    "devetnaest": 19, "dvadeset": 20, "trideset": 30, "cetrdeset": 40, "pedeset": 50,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
_NUM_TOKEN = r"(\d{1,4}(?:[.,]\d{1,2})?|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"


def _to_number(token: str) -> float | None:
    token = token.strip().lower()
    if token in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[token])
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------------
# prices
# ----------------------------------------------------------------------------------------------------
_CUR = r"(?:€|eur(?:o|a|i|os|s)?|evr(?:a|o|i)?)"
_PRICE_RANGE = re.compile(
    r"(?:\bod\s+|\bfrom\s+|\bbetween\s+|\bizmedu\s+)?"
    r"(?:€\s*)?(\d{1,5}(?:[.,]\d{1,2})?)\s*" + _CUR + r"?\s*"
    r"(?:do|to|and|i|-|–|—)\s*"
    r"(?:€\s*)?(\d{1,5}(?:[.,]\d{1,2})?)\s*" + _CUR,
    re.IGNORECASE,
)
_PRICE_RANGE_PREFIX_CUR = re.compile(  # "€40-60", "40€ - 60€"
    r"€\s*(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:do|to|-|–|—)\s*€?\s*(\d{1,5}(?:[.,]\d{1,2})?)", re.IGNORECASE
)
_PRICE_SINGLE = re.compile(r"(?:€\s*(\d{1,5}(?:[.,]\d{1,2})?)|(\d{1,5}(?:[.,]\d{1,2})?)\s*" + _CUR + r")", re.IGNORECASE)


def extract_prices(text: str) -> tuple[float | None, float | None]:
    """'od 40 do 60 eura' → (40, 60); '20 eura po osobi' → (20, 20); '40-60 €' → (40, 60)."""
    t = _norm(text)
    m = _PRICE_RANGE.search(t) or _PRICE_RANGE_PREFIX_CUR.search(t)
    if m:
        lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
        if lo is not None and hi is not None:
            return (min(lo, hi), max(lo, hi))
    m = _PRICE_SINGLE.search(t)
    if m:
        v = _to_number(m.group(1) or m.group(2))
        if v is not None:
            return (v, v)
    return (None, None)


# ----------------------------------------------------------------------------------------------------
# capacity
# ----------------------------------------------------------------------------------------------------
_CAP_NOUN = (
    r"(?:osob[aeu]|osoba|ljudi|gost[aiu]?|gostiju|gosta|person|persons|people|guest|guests|pax|"
    r"putnik[a]?|putnika|ucesnik[a]?|ucesnika|polaznik[a]?|polaznika|lezaj[a]?|lezajeva|kreveta?|beds?|seats?|mjesta)"
)
_CAPACITY = re.compile(r"\b" + _NUM_TOKEN + r"\s+" + _CAP_NOUN + r"\b", re.IGNORECASE)
_CAPACITY_SLEEPS = re.compile(r"\b(?:sleeps|capacity(?: of| for)?|kapacitet(?: je| od)?|primi|prima)\s+(?:do\s+|up to\s+)?" + _NUM_TOKEN, re.IGNORECASE)


def extract_capacity(text: str) -> int | None:
    """'do 4 osobe', 'za 12 ljudi', 'up to 10 people', '4 gosta', 'sleeps 6' → the largest stated number."""
    t = _norm(text)
    values = [_to_number(m.group(1)) for m in _CAPACITY.finditer(t)]
    values += [_to_number(m.group(1)) for m in _CAPACITY_SLEEPS.finditer(t)]
    values = [int(v) for v in values if v is not None and 1 <= v <= 500]
    return max(values) if values else None


# ----------------------------------------------------------------------------------------------------
# season
# ----------------------------------------------------------------------------------------------------
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
# regexes are applied to the diacritic-free lower-cased text; each alternative covers the nominative and the
# genitive/locative forms used after "od … do …" ("od maja do oktobra") plus the Croatian names.
_MONTH_PATTERNS = (
    r"januar\w*|january|sijec\w*",
    r"februar\w*|february|veljac\w*",
    r"mart\w*|march|ozuj\w*",
    r"april\w*|travanj|travnj\w*",
    r"maj[au]?|may|svib\w*",
    r"jun[aiu]?|june|lipanj|lipnj\w*",
    r"jul[aiu]?|july|srpanj|srpnj\w*",
    r"avgust\w*|august|kolovoz\w*",
    r"septemb\w*|september|rujan|rujn\w*",
    r"oktob\w*|october|listopad\w*",
    r"novemb\w*|november|studen\w*",
    r"decemb\w*|december|prosin\w*",
)
_MONTH_RE = [re.compile(r"\b(?:" + p + r")\b") for p in _MONTH_PATTERNS]
_ANY_MONTH = r"(?:" + "|".join(_MONTH_PATTERNS) + r")"
_MONTH_RANGE = re.compile(
    r"\b(?:od|from)\s+(" + _ANY_MONTH + r")\s+(?:do|to|until|till|through)\s+(" + _ANY_MONTH + r")\b"
)
_ALL_YEAR = re.compile(
    r"cijel[eu] godin[eu]|citav[eu] godin[eu]|cele godine|tokom godine|preko cijele godine|all[ -]year|year[ -]round|"
    r"whole year|throughout the year|every season|u svim sezonama|svake sezone"
)
_SEASON_WORDS = (
    (re.compile(r"\bljet\w*|\bleto\b|\bleti\b|\bsummer\b"), "June–September"),
    (re.compile(r"\bzim\w*|\bwinter\b"), "December–February"),
    (re.compile(r"\bproljec\w*|\bprolec\w*|\bspring\b"), "March–May"),
    (re.compile(r"\bjesen\w*|\bautumn\b|\bfall\b"), "September–November"),
)


def _month_index(token: str) -> int | None:
    for i, rx in enumerate(_MONTH_RE):
        if rx.fullmatch(token):
            return i
    return None


def extract_season(text: str) -> str | None:
    """'od maja do oktobra' → 'May–October'; 'cijele godine' → 'all-year'; 'ljeti' → 'June–September'."""
    t = _norm(text)
    m = _MONTH_RANGE.search(t)
    if m:
        a, b = _month_index(m.group(1)), _month_index(m.group(2))
        if a is not None and b is not None:
            return f"{MONTHS_EN[a]}–{MONTHS_EN[b]}"
    if _ALL_YEAR.search(t):
        return "all-year"
    found: list[tuple[int, int]] = []  # (position, month index)
    for i, rx in enumerate(_MONTH_RE):
        for mm in rx.finditer(t):
            found.append((mm.start(), i))
    if found:
        found.sort()
        first, last = found[0][1], found[-1][1]
        return MONTHS_EN[first] if first == last else f"{MONTHS_EN[first]}–{MONTHS_EN[last]}"
    for rx, label in _SEASON_WORDS:
        if rx.search(t):
            return label
    return None


# ----------------------------------------------------------------------------------------------------
# category
# ----------------------------------------------------------------------------------------------------
# (keyword regex on the normalised text, weight). Order of CATEGORIES breaks ties.
_CATEGORY_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "accommodation": [
        (r"apartman\w*", 3), (r"\bsob[aeu]\b|\bsobe\b", 2), (r"smjestaj\w*|smestaj\w*", 3), (r"nocenj\w*|prenocist\w*", 3),
        (r"kuc[aeu] za odmor", 3), (r"\bvil[aeu]\b", 2), (r"\bstudio\b", 1), (r"krevet\w*", 1), (r"po noci|per night", 2),
        (r"apartment\w*", 3), (r"\brooms?\b", 2), (r"accommodation|lodging|guesthouse|guest house|bed and breakfast|b&b", 3),
        (r"\bstay\b|overnight", 1),
    ],
    "food": [
        (r"konob[aeu]|konobi", 3), (r"restoran\w*|restaurant", 3), (r"\bhran[aeu]\b", 2), (r"ruc(?:ak|ka|kovi)|vecer[aeu]|dorucak|dorucka", 2),
        (r"\bjel[aoeu]\b|\bjela\b", 2), (r"kuhinj\w*", 1), (r"domac[aeu] (?:hrana|jela|kuhinja)", 3),
        (r"\bfood\b|\btavern\b|\bmeals?\b|\blunch\b|\bdinner\b|\bbreakfast\b|\bdishes\b|\bcuisine\b", 2), (r"\bwine\b|\bvino\b|\bprsut\w*|\bsir\b|\bcheese\b", 1),
    ],
    "guiding": [
        (r"vodic\w*|vodjen\w*|voden[aiu]\b", 3), (r"\btur[aeu]\b|\bture\b", 2), (r"setnj\w*", 2), (r"izlet\w*", 2),
        (r"planinar\w*|pjesac\w*|pesac\w*", 1), (r"\bguided?\b|\bguiding\b", 3), (r"\btours?\b", 2), (r"\bwalks?\b|\bhik(?:e|es|ing)\b|\btrek\w*", 2),
        (r"excursion\w*", 2),
    ],
    "craft": [
        (r"radionic\w*", 3), (r"zanat\w*", 3), (r"maslinov\w* ulj\w*", 2), (r"tkanj\w*|keramik\w*|grncar\w*|rukotvorin\w*|suvenir\w*", 2),
        (r"workshop\w*", 3), (r"\bcrafts?\b|handmade|hand-made|\bpottery\b|\bweaving\b|olive[ -]oil", 2), (r"souvenir\w*", 1),
    ],
    "transport": [
        (r"prevoz\w*|prijevoz\w*", 3), (r"transfer\w*", 3), (r"taksi|\btaxi\b", 3), (r"\bbrod\w*|\bbark[aeu]\b|\bcam(?:ac|ca|cem)\b", 2),
        (r"\bvoznj\w*|\bbicikl\w*", 1), (r"\btransport\b|\bshuttle\b|\bboat\b|\bbike rental\b|\brides?\b", 2),
    ],
    "experience": [
        (r"dozivljaj\w*|iskustv\w*|avantur\w*", 2), (r"kajak\w*|ronjenj\w*|jedrenj\w*|berb[aeu]\b", 2),
        (r"\bexperiences?\b|\badventure\w*", 2), (r"\bkayak\w*|\bdiving\b|\bsailing\b|\bharvest\w*", 2),
    ],
}
_CATEGORY_RE = {c: [(re.compile(p), w) for p, w in kws] for c, kws in _CATEGORY_KEYWORDS.items()}


def extract_category(text: str) -> tuple[str, dict[str, int]]:
    """Weighted keyword vote → (category, scores). 'other' when nothing matches."""
    t = _norm(text)
    scores: dict[str, int] = {}
    for cat, rxs in _CATEGORY_RE.items():
        s = 0
        for rx, w in rxs:
            s += w * len(rx.findall(t))
        scores[cat] = s
    best = max(CATEGORIES[:-1], key=lambda c: (scores.get(c, 0), -CATEGORIES.index(c)))
    return (best if scores.get(best, 0) > 0 else "other"), scores


# ----------------------------------------------------------------------------------------------------
# accessibility
# ----------------------------------------------------------------------------------------------------
_ACCESS_RE = re.compile(
    r"stepenic\w*|stepenik\w*|stepenist\w*|bez stepenic\w*|kolic\w*|invalid\w*|pristupac\w*|prizemlj\w*|\blift\w*|"
    r"\brampa?\w*|prilaz\w*|sirin[aeu] vrata|\bwheelchair\w*|\bsteps?\b|\bstairs?\b|\bstaircase\b|\baccessib\w*|"
    r"ground floor|\bramps?\b|\belevator\b|level access|\bmobility\b|\bstep-free\b"
)


def extract_accessibility(text: str) -> str:
    """Sentences that talk about steps, wheelchairs, ground floors, lifts, ramps… (max ~300 chars)."""
    picked = [s for s in _sentences(text) if _ACCESS_RE.search(_norm(s))]
    return _truncate_words(" ".join(picked), 300) if picked else ""


# ----------------------------------------------------------------------------------------------------
# title and description
# ----------------------------------------------------------------------------------------------------
_OFFER_VERB = re.compile(
    r"^(?:ja\s+|mi\s+|we\s+|i\s+|my family\s+|moja porodica\s+)?"
    r"(?:izdajem[o]?|iznajmljujem[o]?|nudim[o]?|imam[o]?|organizujem[o]?|organiziram[o]?|vodim[o]?|drzim[o]?|"
    r"pravim[o]?|spremam[o]?|kuvam[o]?|kuham[o]?|prodajem[o]?|radim[o]?|otvaram[o]?|vozim[o]?|"
    r"rent out|rent|offer|have|run|organi[sz]e|lead|guide|make|cook|host|provide|sell|operate)\s+(.+)$",
    re.IGNORECASE,
)
_LEADING_FILLER = re.compile(r"^(?:jedan|jednu|jedno|a|an|the|one|our|nas|nasu|nase|svoj|svoju|svoje)\s+", re.IGNORECASE)
_GREETING = re.compile(
    r"^(?:dobar dan|dobro jutro|dobro vece|dobro vecer|zdravo|pozdrav|cao|hello|hi|hey|good morning|good afternoon|good evening)\b[.!,]*\s*",
    re.IGNORECASE,
)
_SELF_INTRO = re.compile(r"^(?:ja sam|zovem se|moje ime je|my name is|i am|i'm|this is)\b", re.IGNORECASE)
_DISCLAIMER = re.compile(r"izmisljen|prototip|fictional|prototype|not a real provider|nije stvarni", re.IGNORECASE)


def _clean_sentences(text: str) -> list[str]:
    """Drop the greeting and a self-introduction ("ja sam …", "my name is …") so that no name lands
    in the public description; drop the prototype disclaimer sentence used in the fixtures."""
    out: list[str] = []
    for i, s in enumerate(_sentences(text)):
        if i == 0:
            s = _GREETING.sub("", s).strip()
            if not s:
                continue
        if i < 2 and _SELF_INTRO.match(_norm(s)):
            continue
        if _DISCLAIMER.search(_norm(s)):
            continue
        out.append(s)
    return out


def extract_title(text: str, category: str, *, language: str, host_display_name: str = "") -> str:
    """First clause that names the offer ("Izdajem apartman u Donjoj Lastvi" → "Apartman u Donjoj Lastvi")."""
    sentences = _clean_sentences(text)
    cat_rxs = _CATEGORY_RE.get(category, [])
    candidate = ""
    for s in sentences:
        for clause in _clauses(s):
            m = _OFFER_VERB.match(clause)
            if m:
                candidate = m.group(1)
                break
        if candidate:
            break
    if not candidate:
        for s in sentences:
            for clause in _clauses(s):
                n = _norm(clause)
                if any(rx.search(n) for rx, _ in cat_rxs):
                    candidate = _OFFER_VERB.sub(lambda mm: mm.group(1), clause)
                    break
            if candidate:
                break
    candidate = _LEADING_FILLER.sub("", candidate.strip(" .!?"))
    if candidate and len(candidate) >= 3:
        return _truncate_words(_cap_first(candidate), TITLE_MAX_CHARS)
    local_label, en_label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["other"])
    label = en_label if language == "en" else local_label
    return f"{label} — {host_display_name}".strip(" —") if host_display_name else label


def extract_description(text: str, limit: int = DESCRIPTION_MAX_CHARS) -> str:
    """The cleaned transcript, cut at a sentence boundary near ``limit`` characters."""
    out = ""
    for s in _clean_sentences(text):
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    if len(out) > limit:
        out = _truncate_words(out, limit)
    return out


# ----------------------------------------------------------------------------------------------------
# missing fields
# ----------------------------------------------------------------------------------------------------
def _has_text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def compute_missing_fields(fields: dict[str, Any]) -> list[str]:
    """Every required field that is still empty, in REQUIRED_FIELDS order. Shared with the confirm step."""
    missing: list[str] = []
    if not (_has_text(fields.get("title_local")) or _has_text(fields.get("title_en"))):
        missing.append("title")
    if not (_has_text(fields.get("description_local")) or _has_text(fields.get("description_en"))):
        missing.append("description")
    if not _has_text(fields.get("category")):
        missing.append("category")
    if fields.get("price_min") is None and fields.get("price_max") is None:
        missing.append("price_range")
    if not _has_text(fields.get("season")):
        missing.append("season")
    if fields.get("capacity") is None:
        missing.append("capacity")
    if not (_has_text(fields.get("accessibility_local")) or _has_text(fields.get("accessibility_en"))):
        missing.append("accessibility")
    if fields.get("lat") is None or fields.get("lng") is None:
        missing.append("coordinates")
    return missing


def empty_fields() -> dict[str, Any]:
    return {
        "title_local": "", "title_en": "", "description_local": "", "description_en": "", "category": "other",
        "price_min": None, "price_max": None, "currency": "EUR", "season": None, "capacity": None,
        "accessibility_local": "", "accessibility_en": "", "lat": None, "lng": None,
    }


# ----------------------------------------------------------------------------------------------------
# rules path
# ----------------------------------------------------------------------------------------------------
def extract_rules(transcript: str, language: str = "cnr", *, host_display_name: str = "") -> dict[str, Any]:
    """Deterministic extraction. ``language`` is the language the host spoke; the other language gets a
    copy of the text and ``translation_pending`` is True."""
    fields = empty_fields()
    category, _scores = extract_category(transcript)
    price_min, price_max = extract_prices(transcript)
    title = extract_title(transcript, category, language=language, host_display_name=host_display_name)
    description = extract_description(transcript)
    accessibility = extract_accessibility(transcript)
    fields.update(
        {
            "category": category, "price_min": price_min, "price_max": price_max, "currency": "EUR",
            "season": extract_season(transcript), "capacity": extract_capacity(transcript),
        }
    )
    # the spoken language fills its own side; the other side is a copy, flagged as pending translation
    if language == "en":
        fields.update(title_en=title, description_en=description, accessibility_en=accessibility)
        fields.update(title_local=title, description_local=description, accessibility_local=accessibility)
    else:
        fields.update(title_local=title, description_local=description, accessibility_local=accessibility)
        fields.update(title_en=title, description_en=description, accessibility_en=accessibility)
    return {
        "fields": fields,
        "missing_fields": compute_missing_fields(fields),
        "extraction_method": "rules",
        "translation_pending": True,
        "llm_provider": "none",
    }


# ----------------------------------------------------------------------------------------------------
# LLM path
# ----------------------------------------------------------------------------------------------------
_SYSTEM_PROMPT = """You turn a small tourism provider's spoken description (a speech-to-text transcript) into a structured listing.
The provider lives on the Vrmac peninsula (Bay of Kotor, Montenegro). Transcripts are in Montenegrin (Latin script,
close to Serbian/Croatian) or English.

Return ONE JSON object and nothing else, with exactly these keys:
  title_local (string, Montenegrin, max 90 chars), title_en (string, English),
  description_local (string, Montenegrin, 2-5 sentences), description_en (string, English translation),
  category (one of: accommodation, food, guiding, craft, experience, transport, other),
  price_min (number or null), price_max (number or null), currency (3-letter code, usually "EUR"),
  season (string like "May–October", "all-year", or null), capacity (integer number of people or null),
  accessibility_local (string, Montenegrin; "" if not mentioned), accessibility_en (string, English; "" if not mentioned),
  missing_fields (array of strings from: title, description, category, price_range, season, capacity, accessibility, coordinates).

Rules: use only facts stated in the transcript — never invent prices, capacity, seasons or accessibility. Write the text
in both languages (translate faithfully). Do not include the speaker's name or contact details anywhere. Do not add
coordinates; always list "coordinates" in missing_fields. A single price ("20 euros per person") is price_min = price_max."""


def _num_or_none(v: Any, *, integer: bool = False, lo: float = 0, hi: float = 1e6) -> float | int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    try:
        n = float(str(v).replace(",", ".").replace("€", "").strip())
    except ValueError:
        return None
    if not (lo <= n <= hi):
        return None
    return int(round(n)) if integer else round(n, 2)


def _str(v: Any, limit: int) -> str:
    if v is None:
        return ""
    s = " ".join(str(v).split())
    return s[:limit]


def clean_llm_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the model output: types, ranges, enumerations. Unknown keys are ignored."""
    f = empty_fields()
    f["title_local"] = _str(raw.get("title_local"), 255)
    f["title_en"] = _str(raw.get("title_en"), 255)
    f["description_local"] = _str(raw.get("description_local"), 4000)
    f["description_en"] = _str(raw.get("description_en"), 4000)
    cat = _str(raw.get("category"), 32).lower()
    f["category"] = cat if cat in CATEGORIES else "other"
    f["price_min"] = _num_or_none(raw.get("price_min"))
    f["price_max"] = _num_or_none(raw.get("price_max"))
    if f["price_min"] is not None and f["price_max"] is not None and f["price_min"] > f["price_max"]:
        f["price_min"], f["price_max"] = f["price_max"], f["price_min"]
    if f["price_min"] is None and f["price_max"] is not None:
        f["price_min"] = f["price_max"]
    if f["price_max"] is None and f["price_min"] is not None:
        f["price_max"] = f["price_min"]
    cur = _str(raw.get("currency"), 3).upper()
    f["currency"] = cur if re.fullmatch(r"[A-Z]{3}", cur or "") else "EUR"
    season = _str(raw.get("season"), 64)
    f["season"] = season or None
    f["capacity"] = _num_or_none(raw.get("capacity"), integer=True, lo=1, hi=500)
    f["accessibility_local"] = _str(raw.get("accessibility_local"), 2000)
    f["accessibility_en"] = _str(raw.get("accessibility_en"), 2000)
    f["lat"], f["lng"] = None, None  # the host places the pin on the map; the model must not guess
    return f


def extract_llm(transcript: str, language: str = "cnr", *, host_display_name: str = "") -> dict[str, Any]:
    """LLM extraction with the rules result as safety net for empty fields. Raises LLMUnavailable / ValueError
    when the model is down or does not return a usable JSON object (the caller falls back to rules)."""
    llm = get_llm()
    user = (
        f"Transcript language: {'English' if language == 'en' else 'Montenegrin (Latin script)'}.\n"
        f"Transcript:\n\"\"\"\n{transcript.strip()}\n\"\"\"\n\nReturn the JSON object now."
    )
    reply = llm.complete(_SYSTEM_PROMPT, user, json_mode=True, max_tokens=900, temperature=0.1)
    try:
        raw = parse_json_object(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"LLM returned no JSON object ({exc})") from exc
    fields = clean_llm_fields(raw)
    rules = extract_rules(transcript, language, host_display_name=host_display_name)["fields"]
    for k, v in fields.items():  # back-fill what the model left empty with the deterministic result
        if (v is None or v == "") and rules.get(k) not in (None, ""):
            fields[k] = rules[k]
    if fields["category"] == "other" and rules["category"] != "other":
        fields["category"] = rules["category"]
    translation_pending = not (fields["title_en"].strip() and fields["description_en"].strip()) or (
        fields["description_en"].strip() == fields["description_local"].strip()
    )
    return {
        "fields": fields,
        "missing_fields": compute_missing_fields(fields),
        "extraction_method": "llm",
        "translation_pending": translation_pending,
        "llm_provider": llm.name,
    }


# ----------------------------------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------------------------------
def extract_listing(transcript: str, language: str = "cnr", *, host_display_name: str = "") -> dict[str, Any]:
    """LLM when configured and reachable, otherwise rules. Always returns the documented shape."""
    if language not in ("cnr", "en"):
        language = "cnr"
    llm = get_llm()
    if llm.name != "none":
        try:
            result = extract_llm(transcript, language, host_display_name=host_display_name)
            log.info("listing extracted with llm=%s missing=%s", llm.name, result["missing_fields"])
            return result
        except (LLMUnavailable, ValueError, KeyError, TypeError) as exc:
            log.warning("LLM extraction failed (%s); falling back to rules", exc.__class__.__name__)
    result = extract_rules(transcript, language, host_display_name=host_display_name)
    result["llm_provider"] = llm.name
    log.info("listing extracted with rules (llm=%s) missing=%s", llm.name, result["missing_fields"])
    return result
