"""Draft a listing **title and description** from the host's own spoken words — and nothing else.

The expanded brief is explicit: the model may only *rephrase what the host said* into a title and a
description. **Price, dates/season, capacity and accessibility are never inferred.** They are asked as
explicit form fields, filled in by the host and confirmed by the host before the listing is created
(``Listing.confirmed_fields``, see ``services/onboarding.confirm``). This module therefore has no
price, season, capacity, accessibility, coordinate or category detection at all — an earlier prototype
had them and they were removed on purpose. ``fields_required`` is the list handed back to the UI so it
can ask for those fields.

Two paths, one output shape:

* **LLM** (``LLM_PROVIDER`` = eu_api | ollama | vllm): one JSON object with four string keys. The
  system prompt forbids inventing facts and forbids emitting prices, dates, capacity or accessibility;
  anything else the model returns is dropped by :func:`clean_draft_fields`.
* **Rules** (``LLM_PROVIDER=none``, the model is unreachable, invalid JSON, or the monthly spend cap is
  reached): deterministic. The title is a short clause of the transcript (or a *category-neutral*
  label plus the village name), the description is the tidied transcript cut at ~600 characters. The
  rules path cannot translate, so it copies the local text into the ``*_en`` fields and sets
  ``translation_pending`` — the UI and the validator say so honestly rather than pretending.

Output::

    {
      "fields": {"title_local", "title_en", "description_local", "description_en"},
      "extraction_method": "llm" | "rules",
      "translation_pending": bool,
      "fields_required": [...],          # what the HOST must still fill in and confirm
      "llm_provider": "eu_api" | "ollama" | "none" | ...,
    }

Nothing here logs the transcript or a name: the greeting and a self-introduction ("ja sam …",
"my name is …") are stripped before the description is built, so no personal name reaches a public
listing.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from ..providers.llm import LLMUnavailable, get_llm, parse_json_object
from . import budget

log = logging.getLogger(__name__)

#: The only keys this module is allowed to produce.
FIELD_NAMES: tuple[str, ...] = ("title_local", "title_en", "description_local", "description_en")

#: Structured fields the **host** must fill in and confirm. A model never fills them; the confirm step
#: rejects a listing whose price/season/capacity/accessibility/coordinates were not confirmed.
FIELDS_REQUIRED: tuple[str, ...] = (
    "price_min", "price_max", "currency", "season", "capacity", "accessibility",
    "coordinates", "category", "village",
)

#: Keys that must never appear in an extraction result — asserted in tests and stripped at runtime.
FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset(
    {
        "price", "price_min", "price_max", "price_range", "currency", "cost",
        "season", "season_from", "season_to", "season_all_year", "dates", "availability",
        "capacity", "guests", "beds", "sleeps",
        "accessibility", "accessibility_local", "accessibility_en", "accessibility_step_free",
        "accessibility_note_local", "accessibility_note_en", "step_free",
        "lat", "lng", "coordinates", "category",
    }
)

TITLE_MAX_CHARS = 90
DESCRIPTION_MAX_CHARS = 600

#: Deliberately *category-neutral*: the category is a host-chosen field, so the fallback title must
#: not imply one ("Ponuda"/"Offer", never "Apartman"/"Accommodation").
NEUTRAL_LABEL = {"cnr": "Ponuda", "en": "Offer"}


# --------------------------------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------------------------------
_FOLD_MAP = str.maketrans({"đ": "d", "Đ": "D", "ß": "ss", "ł": "l", "Ł": "L"})


def ascii_fold(text: str) -> str:
    """'Donja Lastva, pješačenje, đak' → 'Donja Lastva, pjesacenje, dak'. Keeps case."""
    text = text.translate(_FOLD_MAP)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _norm(text: str) -> str:
    """Lower-cased, diacritics removed, whitespace collapsed — the matching form of a transcript."""
    return " ".join(ascii_fold(text).lower().split())


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join((text or "").split()))
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


_OFFER_VERB = re.compile(
    r"^(?:ja\s+|mi\s+|we\s+|i\s+|my family\s+|moja porodica\s+)?"
    r"(?:izdajem[o]?|iznajmljujem[o]?|nudim[o]?|imam[o]?|organizujem[o]?|organiziram[o]?|vodim[o]?|drzim[o]?|"
    r"pravim[o]?|spremam[o]?|kuvam[o]?|kuham[o]?|prodajem[o]?|radim[o]?|otvaram[o]?|vozim[o]?|"
    r"rent out|rent|offer|have|run|organi[sz]e|lead|guide|make|cook|host|provide|sell|operate)\s+(.+)$",
    re.IGNORECASE,
)
_LEADING_FILLER = re.compile(
    r"^(?:jedan|jednu|jedno|a|an|the|one|our|nas|nasu|nase|svoj|svoju|svoje)\s+", re.IGNORECASE
)
_GREETING = re.compile(
    r"^(?:dobar dan|dobro jutro|dobro vece|dobro vecer|zdravo|pozdrav|cao|hello|hi|hey|"
    r"good morning|good afternoon|good evening)\b[.!,]*\s*",
    re.IGNORECASE,
)
_SELF_INTRO = re.compile(r"^(?:ja sam|zovem se|moje ime je|my name is|i am|i'm|this is)\b", re.IGNORECASE)
_DISCLAIMER = re.compile(r"izmisljen|prototip|fictional|prototype|not a real provider|nije stvarni", re.IGNORECASE)


def clean_sentences(text: str) -> list[str]:
    """Sentences of the transcript minus the greeting, a self-introduction and the fixture disclaimer.

    The self-introduction is dropped so that **no personal name** ends up in a public description;
    the disclaimer sentence of the sample transcripts is dropped because it describes the prototype,
    not the offer (the listing itself is flagged ``is_sample``).
    """
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


# --------------------------------------------------------------------------------------------------
# rules path — title and description only
# --------------------------------------------------------------------------------------------------
def rules_title(transcript: str, *, language: str = "cnr", village_name: str = "") -> str:
    """A short clause of the host's own words ("Izdajem apartman u Donjoj Lastvi" → "Apartman u
    Donjoj Lastvi"); otherwise a *category-neutral* label plus the village name."""
    for sentence in clean_sentences(transcript):
        for clause in _clauses(sentence):
            m = _OFFER_VERB.match(clause)
            if not m:
                continue
            candidate = _LEADING_FILLER.sub("", m.group(1).strip(" .!?"))
            if len(candidate) >= 3:
                return _truncate_words(_cap_first(candidate), TITLE_MAX_CHARS)
    label = NEUTRAL_LABEL.get(language, NEUTRAL_LABEL["cnr"])
    return f"{label} — {village_name}".strip(" —") if village_name else label


def rules_description(transcript: str, limit: int = DESCRIPTION_MAX_CHARS) -> str:
    """The tidied transcript, cut at a sentence boundary near ``limit`` characters."""
    out = ""
    for s in clean_sentences(transcript):
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return _truncate_words(out, limit)


def empty_fields() -> dict[str, str]:
    return {k: "" for k in FIELD_NAMES}


def draft_rules(transcript: str, language: str = "cnr", *, village_name: str = "") -> dict[str, Any]:
    """Deterministic draft. Cannot translate: the other language is a copy, flagged pending."""
    title = rules_title(transcript, language=language, village_name=village_name)
    description = rules_description(transcript)
    fields = empty_fields()
    if language == "en":
        fields.update(title_en=title, description_en=description, title_local=title, description_local=description)
    else:
        fields.update(title_local=title, description_local=description, title_en=title, description_en=description)
    return {
        "fields": fields,
        "extraction_method": "rules",
        "translation_pending": True,
        "fields_required": list(FIELDS_REQUIRED),
        "llm_provider": get_llm().name,
    }


# --------------------------------------------------------------------------------------------------
# LLM path — title and description only
# --------------------------------------------------------------------------------------------------
SYSTEM_PROMPT = """You help a small rural tourism provider on the Vrmac peninsula (Bay of Kotor, Montenegro) \
publish an offer. You are given a speech-to-text transcript of the provider speaking, in Montenegrin \
(Latin script, close to Serbian/Croatian) or in English.

Your ONLY task is to rephrase the provider's OWN WORDS into a short title and a readable description, in \
both languages.

Return ONE JSON object and nothing else, with exactly these four keys:
  "title_local"       - Montenegrin (Latin script), max 90 characters, no full stop
  "title_en"          - the same title in English
  "description_local" - Montenegrin, 2-5 sentences, only what the provider said
  "description_en"    - a faithful English translation of description_local

Hard rules:
1. Use ONLY facts stated in the transcript. Never invent, guess, embellish or add a fact - not a view, not a
   distance, not a service. If the transcript does not say it, it does not exist.
2. Do NOT output prices, amounts of money, dates, months, seasons, availability, capacity, number of guests
   or beds, or accessibility statements as separate values. Those are asked from the provider as explicit
   form fields and confirmed by the provider; you must not produce them and must not put them in any other
   key. (Sentences the provider actually spoke may of course stay inside the description as their own words.)
3. Do NOT output any other key - no category, no coordinates, no price, no season, no capacity, no
   accessibility. Exactly the four keys above.
4. Never include the speaker's name, phone number, e-mail address or any contact detail.
5. Keep the provider's voice. Do not write marketing language."""


def _str(v: Any, limit: int) -> str:
    if v is None:
        return ""
    return " ".join(str(v).split())[:limit]


def clean_draft_fields(raw: dict[str, Any]) -> dict[str, str]:
    """Keep exactly the four allowed keys; everything else the model produced is discarded."""
    extra = sorted(k for k in raw if k not in FIELD_NAMES)
    if extra:
        log.warning("extraction: dropped %d disallowed key(s) from the model reply: %s", len(extra), extra)
    return {
        "title_local": _str(raw.get("title_local"), TITLE_MAX_CHARS),
        "title_en": _str(raw.get("title_en"), TITLE_MAX_CHARS),
        "description_local": _str(raw.get("description_local"), 4000),
        "description_en": _str(raw.get("description_en"), 4000),
    }


def draft_llm(
    transcript: str, language: str = "cnr", *, village_name: str = "", db: Session | None = None
) -> dict[str, Any]:
    """LLM draft with the rules result as a safety net for empty fields.

    Raises :class:`~app.providers.llm.LLMUnavailable` or ``ValueError`` when the model is down or does
    not return a usable JSON object; the caller then falls back to the rules path.
    """
    llm = get_llm()
    user = (
        f"Transcript language: {'English' if language == 'en' else 'Montenegrin (Latin script)'}.\n"
        f"Transcript:\n\"\"\"\n{transcript.strip()}\n\"\"\"\n\n"
        "Return the JSON object with the four keys now."
    )
    reply = llm.complete(SYSTEM_PROMPT, user, json_mode=True, max_tokens=700, temperature=0.1)
    if db is not None:
        budget.record(db, reply, "extraction")
    try:
        raw = parse_json_object(reply.text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"LLM returned no JSON object ({exc})") from exc
    fields = clean_draft_fields(raw)
    fallback = draft_rules(transcript, language, village_name=village_name)["fields"]
    for k, v in fields.items():
        if not v.strip():
            fields[k] = fallback[k]
    translation_pending = not (fields["title_en"].strip() and fields["description_en"].strip()) or (
        fields["description_en"].strip() == fields["description_local"].strip()
    )
    return {
        "fields": fields,
        "extraction_method": "llm",
        "translation_pending": translation_pending,
        "fields_required": list(FIELDS_REQUIRED),
        "llm_provider": llm.name,
    }


# --------------------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------------------
def draft_title_and_description(
    transcript: str, language: str = "cnr", *, village_name: str = "", db: Session | None = None
) -> dict[str, Any]:
    """Title and description only. LLM when configured, reachable and within budget; else rules.

    ``db`` is optional: when it is given the paid call is guarded by the monthly spend cap
    (:func:`app.services.budget.guard`) and its token usage is recorded. When the cap is reached the
    deterministic rules path is used — the host is never blocked from publishing, and no unsourced
    text is produced.
    """
    if language not in ("cnr", "en"):
        language = "cnr"
    transcript = (transcript or "").strip()
    llm = get_llm()
    if llm.name != "none" and transcript:
        try:
            if db is not None:
                budget.guard(db, "extraction")
            result = draft_llm(transcript, language, village_name=village_name, db=db)
            log.info("draft written with llm=%s translation_pending=%s", llm.name, result["translation_pending"])
            return result
        except budget.SpendCapReached as exc:
            log.warning("spend cap reached (%.2f €) — drafting with the rules path instead", exc.spent)
        except (LLMUnavailable, ValueError, KeyError, TypeError) as exc:
            log.warning("LLM draft failed (%s); falling back to the rules path", exc.__class__.__name__)
    result = draft_rules(transcript, language, village_name=village_name)
    log.info("draft written with the rules path (llm=%s)", llm.name)
    return result
