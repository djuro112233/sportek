"""Question relevance: does the evidence behind an answer actually address the question?

The verifier checks that every sentence is *supported* by its cited chunk. It does not check
that the chunk is *about the question*: an extractive or drifting model can answer "what is
good for knee pain" with verbatim, well-cited sentences about pain in pregnancy. This module
scores how much of the question's content the cited evidence covers, weighting each question
term by its rarity in the knowledge base (a question term the knowledge base never uses is
strong evidence that the question is off the knowledge base).

``relevance = sum(idf(term) for matched terms) / sum(idf(term) for all question terms)``

Terms are 5-character stems of :func:`app.core.verifier.content_tokens` minus question words.
``None`` means "not assessable": the question has no content terms, or the evidence is in a
different language family than the question (cross-lingual relevance needs the LLM judge;
documented in docs/safety.md).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable

from app.core.i18n import coerce_lang, is_bcms, normalize_text
from app.core.types import AnswerSentence, RetrievedChunk
from app.core.verifier import content_tokens

STEM_LEN = 5

# Question words and generic verbs that carry no topic (normalised, diacritic-free).
QUESTION_WORDS: frozenset[str] = frozenset(
    {
        "sta", "sto", "kako", "zasto", "gdje", "gde", "kada", "koliko", "koji", "koja", "koje", "koju",
        "kojim", "kojih", "mogu", "moze", "mozes", "mozemo", "moci", "treba", "trebam", "trebalo",
        "imam", "imas", "ima", "imati", "imala", "imao", "radim", "raditi", "uradim", "uraditi",
        "uradila", "smijem", "smem", "smije", "sme", "normalno", "dobro", "lose", "znaci", "pitanje",
        "molim", "hvala", "zanima", "interesuje", "reci", "kazi", "kazes", "jesam", "jeste", "jesu",
        "bude", "biti", "bila", "bilo", "bio", "nesto", "nekad", "ponekad", "uvijek", "uvek", "danas",
        "jutros", "sinoc", "sutra", "juce", "jucer", "godin", "godina", "godine", "dana", "dan",
        "what", "which", "how", "why", "where", "when", "who", "should", "could", "would", "can",
        "may", "need", "want", "know", "tell", "please", "thanks", "thank", "okay", "normal", "good",
        "bad", "mean", "means", "something", "anything", "really", "just", "like", "get", "got",
        "make", "made", "take", "took", "think", "feel", "felt", "say", "said", "does", "doing",
        "done", "being", "year", "years", "day", "days", "today", "yesterday", "tomorrow",
        "znam", "znas", "znati", "znamo", "uzme", "uzmem", "uzeti", "uzima", "uzimati", "uzimam",
        "koristi", "koristim", "koristiti", "use", "using", "used",
        # numbers and generic nouns carry no topic ("six people", "dvije osobe")
        "jedan", "jedna", "jedno", "dva", "dvije", "dve", "tri", "cetiri", "pet", "sest", "sedam", "osam",
        "devet", "deset", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "ljudi", "ljude", "osoba", "osobe", "osobu", "people", "person", "persons", "someone", "somebody",
        "stvari", "stvar", "things", "thing", "nacin", "way", "ways", "dobar", "dobra", "najbolji",
        "najbolja", "najbolje", "best", "great",
    }
)  # fmt: skip

# A question term the knowledge base never uses is strong evidence the question is off the
# knowledge base; relevance is multiplied by this factor when such a term stays unmatched.
UNKNOWN_TERM_PENALTY = 0.85

IdfFn = Callable[[str], float]


_YAT_RE = re.compile(r"(?<=[bcdfghklmnprstvz])i?je")

# Domain thesaurus applied to question and evidence alike before stemming, so paraphrases a
# user is likely to type map onto the knowledge base's wording. Phrases first (on normalised
# text), then single tokens. Canonical forms are chosen so their 5-character stem is distinct.
_PHRASE_SYNONYMS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rx), repl)
    for rx, repl in (
        (r"\bzastit\w* (?:od|protiv) trudnoc\w*", "kontracepcija"),
        (r"\bsredstv\w* za zastitu\b", "kontracepcija"),
        (r"\bbirth control\b", "contraception"),
        (r"\bmorning after pill\b", "emergency contraception"),
        (r"\bpilul\w* za dan posl\w*", "hitna kontracepcija"),
        (r"\bpolno prenosiv\w*|\bspolno prenosiv\w*|\bpoln\w* bolest\w*|\bspoln\w* bolest\w*|\bvenericn\w*", "ppi"),
        (r"\bsexually transmitted\w*|\bstds?\b|\bstis?\b", "sti"),
        (r"\bbebi bluz\b|\bbaby blues\b", "bebibluz"),
        (r"\bcheck ?ups?\b|\bantenatal (?:visits?|contacts?|appointments?)\b", "visit"),
        (r"\bkod (?:doktor|ljekar|lekar|lijecni|ginekolog)\w*", "pregled"),
        (r"\bpupcan\w* vrpc\w*|\bpupcanik\w*|\bpupak\b|\bpupka\b", "pupcana"),
        (r"\bumbilical cord\b|\bcord stump\b|\bbelly button\b", "umbilical"),
    )
)
_TOKEN_SYNONYMS: dict[str, str] = {}
for canonical, variants in {
    "lekar": ("doktor", "doktora", "doktoru", "doktorka", "doktorica", "ljekar", "ljekara", "ljekaru", "lekar", "lekara",
              "lekaru", "lijecnik", "lijecnika", "lijecniku", "ginekolog", "ginekologa", "ginekologu", "ginekologinja", "babica"),
    "clinician": ("doctor", "doctors", "clinician", "clinicians", "midwife", "midwives", "nurse", "nurses", "gp", "physician"),
    "pregled": ("pregled", "pregleda", "pregledi", "preglede", "kontrola", "kontrole", "kontrolu", "kontrola", "posjeta", "posjete", "poseta", "posete"),
    "visit": ("visit", "visits", "appointment", "appointments", "contact", "contacts", "checkup", "checkups"),
    "dojenje": ("dojenje", "dojenja", "doji", "dojim", "dojiti", "dojenjem", "podoj", "podoja", "sisa", "sisanje", "sisati", "cica"),
    "breastfeeding": ("breastfeeding", "breastfeed", "breastfed", "nursing", "feeding", "feeds", "latch", "latching"),
    "beba": ("beba", "bebe", "bebu", "bebi", "bebom", "novorodjence", "novorodjenceta", "novorodjencetu", "novorodjene", "dijete", "dete", "djete", "djeteta", "deteta"),
    "baby": ("baby", "babies", "newborn", "newborns", "infant", "infants"),
    "menstruacija": ("menstruacija", "menstruacije", "menstruaciju", "menstruacijom", "mjesecnica", "mjesecnice", "mesecnica", "mesecnice", "ciklus", "ciklusa"),
    "menstruation": ("menstruation", "menstrual", "period", "periods", "cycle", "cycles"),
    "seks": ("seks", "seksa", "odnos", "odnosa", "odnosi", "snosaj", "snosaja", "spavanje"),
    "sex": ("sex", "intercourse"),
    "efikasan": ("efikasan", "efikasna", "efikasne", "efikasno", "najefikasnija", "najefikasnije", "sigurna", "sigurne", "sigurno",
                 "najsigurnija", "najsigurnije", "pouzdan", "pouzdana", "pouzdane", "najpouzdanija", "najpouzdanije", "djelotvorna", "delotvorna"),
    "effective": ("effective", "reliable", "safest", "best", "works"),
    "neplodnost": ("neplodnost", "neplodnosti", "neplodna", "neplodnom", "sterilitet", "steriliteta", "jalovost"),
    "infertility": ("infertility", "infertile", "sterility", "sterile"),
    "povjerljivo": ("povjerljivo", "poverljivo", "povjerljivost", "poverljivost", "tajna", "tajno", "saznati", "sazna", "znati", "zna", "diskretno", "anonimno"),
    "confidential": ("confidential", "confidentiality", "private", "privacy", "secret", "anonymous"),
    "nabaviti": ("nabaviti", "nabavim", "nabavka", "kupiti", "kupim", "dobiti", "dobijem", "uzeti", "uzmem"),
    "get": ("get", "buy", "obtain", "access"),
    "bolnica": ("bolnica", "bolnicu", "bolnici", "hitna", "hitnu", "hitne", "hitno"),
    "hospital": ("hospital", "emergency", "urgent", "urgently"),
    "znak": ("znak", "znaci", "znakovi", "znakove", "simptom", "simptomi", "simptome", "simptoma", "upozorenja", "opasnosti", "opasnost"),
    "sign": ("sign", "signs", "symptom", "symptoms", "warning", "warnings", "danger"),
    "vitamin": ("vitamin", "vitamini", "vitamine", "vitamina", "suplement", "suplementi", "suplemente", "dodaci", "dodatak", "dodatke", "preparati", "preparate"),
    "supplement": ("supplement", "supplements", "vitamins", "vitamin"),
    "hrana": ("hrana", "hranu", "hrane", "jesti", "jedem", "ishrana", "ishranu", "ishrane", "prehrana", "prehranu"),
    "food": ("food", "foods", "eat", "eating", "diet", "nutrition"),
    "porodjaj": ("porodjaj", "porodjaja", "poroda", "porod", "porodu", "porodjaju", "rodila", "rodjenja"),
    "birth": ("birth", "delivery", "labour", "labor", "postpartum", "postnatal"),
    "tuga": ("tuga", "tuzna", "tuzno", "tugu", "depresija", "depresije", "depresivna", "plakanje", "placem", "potistenost"),
    "sad": ("sad", "sadness", "depressed", "depression", "crying", "low"),
    "testiranje": ("testiranje", "testiram", "testirati", "testiranja", "test", "testovi", "analiza", "analize"),
    "testing": ("testing", "test", "tests", "tested", "screening"),
    "roditelji": ("roditelji", "roditeljima", "roditelja", "mama", "mami", "tata", "tati", "majka", "majci", "otac", "ocu"),
    "parents": ("parents", "parent", "mum", "mom", "dad", "mother", "father"),
    "mlijeko": ("mlijeko", "mleko", "mlijeka", "mleka"),
    "milk": ("milk",),
}.items():
    for variant in variants:
        _TOKEN_SYNONYMS[variant] = canonical


def canonicalise(normalised: str) -> str:
    """Apply the domain thesaurus to normalised text (phrases, then tokens)."""
    for rx, repl in _PHRASE_SYNONYMS:
        normalised = rx.sub(repl, normalised)
    return " ".join(_TOKEN_SYNONYMS.get(tok, tok) for tok in normalised.split())


def fold_yat(token: str) -> str:
    """Fold ijekavian reflexes onto the ekavian form so dialect variants share a stem.

    ``nedjelja``/``nedelja`` → ``nedelja``, ``poslije``/``posle`` → ``posle``, ``mlijeko`` →
    ``mleko``, ``ljekar``/``lijecnik``/``lekar`` → ``lekar``/``lecnik``. Only ``je``/``ije``
    after a consonant is folded, so ``jedan`` and ``jesam`` are untouched.
    """
    return _YAT_RE.sub("e", token)


def stems(text: str) -> list[str]:
    """Ordered, de-duplicated stems of the content tokens of ``text`` (question words removed)."""
    seen: list[str] = []
    for tok in content_tokens(canonicalise(normalize_text(text))):
        if tok in QUESTION_WORDS:
            continue
        stem = fold_yat(tok)[:STEM_LEN]
        if stem not in seen:
            seen.append(stem)
    return seen


def make_idf(documents: Iterable[Iterable[str]]) -> IdfFn:
    """Inverse document frequency over stem sets. Unknown stems get the maximum idf."""
    df: dict[str, int] = {}
    n_docs = 0
    for doc in documents:
        n_docs += 1
        for stem in set(doc):
            df[stem] = df.get(stem, 0) + 1
    ceiling = math.log(1.0 + (n_docs + 0.5) / 0.5) if n_docs else 1.0

    def idf(stem: str) -> float:
        n = df.get(stem)
        if n is None:
            return ceiling
        return math.log(1.0 + (n_docs - n + 0.5) / (n + 0.5))

    idf.ceiling = ceiling  # type: ignore[attr-defined]  # stems at the ceiling are unknown to the corpus
    return idf


def coverage(
    question: str,
    evidence_texts: Iterable[str],
    idf: IdfFn | None = None,
    *,
    unknown_term_penalty: float = UNKNOWN_TERM_PENALTY,
) -> float | None:
    """Rarity-weighted share of the question's stems that occur in the evidence; ``None`` if no stems.

    When ``idf`` knows the corpus (see :func:`make_idf`) and a question stem is both unknown to
    the corpus and unmatched, the score is multiplied by ``unknown_term_penalty``.
    """
    q = stems(question)
    if not q:
        return None
    weight: IdfFn = idf or (lambda _s: 1.0)
    evidence = set()
    for text in evidence_texts:
        evidence.update(stems(text))
    total = sum(weight(s) for s in q)
    if total <= 0.0:
        return None
    matched = sum(weight(s) for s in q if s in evidence)
    score = matched / total
    ceiling = getattr(idf, "ceiling", None)
    if ceiling is not None and any(s not in evidence and weight(s) >= ceiling - 1e-9 for s in q):
        score *= unknown_term_penalty
    return round(score, 4)


def _cited(sentence: AnswerSentence, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    found: list[RetrievedChunk] = []
    for marker in sentence.citations:
        digits = marker[1:]
        if digits.isdigit() and 0 < int(digits) <= len(chunks):
            chunk = chunks[int(digits) - 1]
            if chunk not in found:
                found.append(chunk)
    return found


def _usable(sentences: list[AnswerSentence]) -> list[AnswerSentence]:
    return [s for s in sentences if s.supported and not s.flagged_medication]


def evidence_shares_language(lang: str, sentences: list[AnswerSentence], chunks: list[RetrievedChunk]) -> bool:
    """True when at least one chunk cited by a supported sentence is in the question's language family."""
    family_bcms = is_bcms(coerce_lang(lang))
    for sentence in _usable(sentences):
        for chunk in _cited(sentence, chunks):
            if is_bcms(coerce_lang(chunk.lang)) == family_bcms:
                return True
    return False


def sentence_relevance(
    question: str,
    sentences: list[AnswerSentence],
    chunks: list[RetrievedChunk],
    idf: IdfFn | None = None,
    *,
    unknown_term_penalty: float = UNKNOWN_TERM_PENALTY,
) -> dict[int, float]:
    """Per-sentence relevance: coverage of the question by the sentence plus the heading path of
    the chunks it cites. Keyed by sentence index; only supported, unflagged sentences with a
    resolvable citation are scored. Empty when the question has no content words."""
    if not stems(question):
        return {}
    scores: dict[int, float] = {}
    for index, sentence in enumerate(sentences):
        if not (sentence.supported and not sentence.flagged_medication):
            continue
        cited = _cited(sentence, chunks)
        if not cited:
            continue
        texts = [sentence.text] + [c.heading_path for c in cited if c.heading_path]
        score = coverage(question, texts, idf, unknown_term_penalty=unknown_term_penalty)
        scores[index] = 0.0 if score is None else score
    return scores


def question_relevance(
    question: str,
    lang: str,
    sentences: list[AnswerSentence],
    chunks: list[RetrievedChunk],
    idf: IdfFn | None = None,
    *,
    unknown_term_penalty: float = UNKNOWN_TERM_PENALTY,
) -> float | None:
    """Relevance of the evidence behind the supported sentences to the question.

    Evidence = the supported sentences' texts plus the heading path and text of every chunk
    they cite, whatever its language: stems are script-agnostic after normalisation and a
    genuinely cross-lingual answer scores low, which fails closed (the pipeline may ask the
    LLM judge instead; see ``AskPipeline._relevance``). Returns ``None`` only when nothing is
    supported or nothing is cited; a question without content words scores 0.0.
    """
    usable = _usable(sentences)
    if not usable:
        return None
    cited: list[RetrievedChunk] = []
    for sentence in usable:
        for chunk in _cited(sentence, chunks):
            if chunk not in cited:
                cited.append(chunk)
    if not cited:
        return None
    texts = [s.text for s in usable] + [f"{c.heading_path} {c.text}" for c in cited]
    score = coverage(question, texts, idf, unknown_term_penalty=unknown_term_penalty)
    return 0.0 if score is None else score
