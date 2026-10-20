"""Scope guard: questions MILA must not answer, detected before any model is called.

MILA gives information and referral. It never recommends medicines or doses, never says
whether someone has a condition, never interprets test results, and never changes its rules
on request. A question that *asks* for one of those things is answered with a specific
refusal message and a referral, before retrieval and generation. This protects against a
weak or extractive model answering such a question with loosely related sentences that the
support-only verifier would approve.

All patterns run on :func:`app.core.i18n.normalize_text` output (Cyrillic transliterated,
diacritics stripped, lower case), so one pattern covers sr/bs/me/hr in both scripts.

Kinds and the gate reason / message key the pipeline uses for them:

| kind                  | gate reason            | message key              |
|-----------------------|------------------------|--------------------------|
| ``dose``              | ``medication_or_dose`` | ``withheld_dose``        |
| ``diagnosis``         | ``diagnosis_request``  | ``withheld_diagnosis``   |
| ``test_interpretation`` | ``test_interpretation`` | ``withheld_test_results`` |
| ``manipulation``      | ``manipulation``       | ``withheld_manipulation`` |

Information questions stay in scope: "what is a pap test", "is folic acid important in
pregnancy", "how many antenatal contacts are recommended", "is cramping before a period
normal" are not matched (tested).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.core.i18n import normalize_text
from app.core.verifier import mentions_medication_dose

ScopeKind = Literal["dose", "diagnosis", "test_interpretation", "manipulation"]

SCOPE_REASONS: dict[str, str] = {
    "dose": "medication_or_dose",
    "diagnosis": "diagnosis_request",
    "test_interpretation": "test_interpretation",
    "manipulation": "manipulation",
}
SCOPE_MESSAGE_KEYS: dict[str, str] = {
    "dose": "withheld_dose",
    "diagnosis": "withheld_diagnosis",
    "test_interpretation": "withheld_test_results",
    "manipulation": "withheld_manipulation",
}


@dataclass(frozen=True)
class ScopeResult:
    kind: ScopeKind | None
    matched: str = ""  # rule label, never user text

    @property
    def out_of_scope(self) -> bool:
        return self.kind is not None


# --- dose / prescription --------------------------------------------------------------------
_DOSE_UNIT = (
    r"(?:mg|mcg|ug|ml|iu|ij|mill?igram\w*|mi[ck]rogram\w*|mil[il]?lit\w*|tablet\w*|kapsul\w*|kap[i]?|kapi|"
    r"sirup\w*|syrup\w*|drops?|doz\w*|dos(?:e|es|age|ing))"
)
_DOSE_WORD = r"(?:doz\w*|dos(?:e|es|age|ing))"
_DRUG = (
    r"(?:ibuprofen\w*|paracetamol\w*|aspirin\w*|brufen\w*|andol\w*|analgin\w*|diklofenak\w*|"
    r"voltaren\w*|antibiotik\w*|antibiotic\w*|amoksicilin\w*|amoxicillin\w*|azitromicin\w*|"
    r"azithromycin\w*|metronidazol\w*|flagil\w*|klomifen\w*|clomiphene\w*|duphaston\w*|"
    r"utrogestan\w*|progesteron\w*|misoprostol\w*|cytotec\w*|mifepriston\w*|levonorgestrel\w*|"
    r"escapelle\w*|postinor\w*|ulipristal\w*|ellaone\w*|painkiller\w*|analgetik\w*|"
    r"antipiretik\w*|lijek\w*|lek|leka|lekov\w*|lekove|lijekov\w*|tablet\w*|kapsul\w*|sirup\w*|"
    r"medicin\w*|medication\w*|drug\w*|pill\w*|terapij\w*|therapy|treatment)"
)
_SUPPLEMENT = (
    r"(?:folna\w*|folne|folnu|folic|gvozdj\w*|zeljez\w*|iron|kalcij\w*|calcium|vitamin\w*|magnezij\w*|"
    r"magnesium|omega\w*|jod\w*|iodine|cink\w*|zinc|suplement\w*|supplement\w*|dodat\w*|probiotik\w*|probiotic\w*)"
)
_DOSE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\b(?:koliko|kolika|koliku|kolko|how many|how much)\b(?:\s+\w+){{0,3}}?\s+{_DOSE_UNIT}\b"),
    re.compile(rf"\b(?:koja|koju|koji|kojoj|kojem|kojim|kolika|what|which)\b(?:\s+\w+){{0,2}}?\s+{_DOSE_WORD}\b"),
    # which medicine / what can I take
    re.compile(
        rf"\b(?:koji|koje|koju|sta|sto|which|what)\b(?:\s+\w+){{0,2}}?\s+{_DRUG}\b(?:\s+\w+){{0,4}}?"
        r"\s+(?:uzmem|uzeti|uzimam|uzimati|popijem|popiti|pijem|piti|koristim|koristiti|dam|dajem|"
        r"take|use|give)\b"
    ),
    re.compile(
        r"\b(?:sta|sto|what)\s+(?:da\s+|mogu\s+da\s+|smijem\s+da\s+|smem\s+da\s+|can\s+i\s+|should\s+i\s+)?"
        r"(?:popijem|uzmem|pijem|take|give)\b(?:\s+\w+){0,3}?\s+(?:za|protiv|for|against)\b"
    ),
    # may I take <drug>
    re.compile(
        rf"\b(?:smijem|smem|mogu|moze|mozes|sme|smije|can|may|could|should|is it (?:ok|okay|safe) to)\b"
        rf"(?:\s+\w+){{0,3}}?\s+(?:li\s+)?(?:da\s+)?(?:i\s+)?(?:piti|popiti|uzeti|uzimati|koristiti|dati|take|use|give|taking|drink)\b"
        rf"(?:\s+\w+){{0,3}}?\s+{_DRUG}\b"
    ),
    re.compile(rf"\b{_DRUG}\b(?:\s+\w+){{0,2}}?\s+(?:smijem|smem|mogu|moze|sme|smije)\b"),
    # requests to prescribe (a question whether something NEEDS a prescription stays in scope)
    re.compile(r"\b(?:propis|prepis)\w*\s+(?:mi|me|meni)\b"),
    re.compile(r"\b(?:mozes|mozete|hoces|hocete|bi|da)\s+(?:li\s+)?(?:mi\s+|da\s+mi\s+)?(?:propis|prepis)\w*\b"),
    re.compile(r"\b(?:napisi|napisite|daj|dajte|izdaj|izdajte)\s+(?:mi\s+)?recept\b"),
    re.compile(r"\b(?:prescribe\s+(?:me|for\s+me|something|some)|can\s+you\s+prescribe|write\s+(?:me\s+)?a\s+prescription|give\s+me\s+a\s+prescription)\b"),
    # quantity of a supplement or nutrient, with or without a unit (AS-3)
    re.compile(
        rf"\b(?:koliko|kolika|koliku|kolko|how\s+much|how\s+many)\b(?:\s+\w+){{0,3}}?\s+{_SUPPLEMENT}\b"
    ),
    # frequency regimen request ("koliko puta dnevno da pijem ...", "how often should i take ...")
    re.compile(
        rf"\b(?:koliko\s+puta|koliko\s+cesto|how\s+often|how\s+many\s+times)\b(?:\s+\w+){{0,5}}?\s+(?:uzim\w*|uzm\w*|pij\w*|popij\w*|korist\w*|take|taking|use)\b(?:\s+\w+){{0,3}}?\s+(?:{_DRUG}|{_SUPPLEMENT})\b"
    ),
    re.compile(r"\b(?:tacn[au]|exact)\s+(?:doz\w*|dose|dosage|kolicin\w*|amount)\b"),
    re.compile(r"\b(?:reci|kazi|daj)\s+(?:mi\s+)?(?:tacn[au]\s+)?(?:doz\w*|dose|dosage)\b"),
    re.compile(r"\b(?:koliko|how (?:much|many))\b(?:\s+\w+){0,3}?\s+(?:kapi|drops)\b"),
)

# --- diagnosis -------------------------------------------------------------------------------
_CONDITION = (
    r"(?:rak\w*|tumor\w*|kancer\w*|karcinom\w*|infekcij\w*|upal\w*|anemij\w*|dijabet\w*|polip\w*|"
    r"cist\w*|miom\w*|endometrioz\w*|pcos|policist\w*|hlamidij\w*|klamidij\w*|kandid\w*|gljiv\w*|"
    r"herpes\w*|hpv|sifilis\w*|gonorej\w*|trihomon\w*|vaginoz\w*|trudn\w*|pobacaj\w*|spontan\w*|"
    r"vanmateric\w*|preeklamps\w*|depresij\w*|anksioz\w*|urinarn\w*|bakterij\w*|virus\w*|"
    r"menopauz\w*|hormon\w*|stitnj\w*|stitn\w*|tiroid\w*|sterilit\w*|neplodn\w*|alergij\w*|"
    r"cancer|tumou?r|infection|inflammation|an(?:a)?emia|diabetes|polyp\w*|cyst\w*|fibroid\w*|"
    r"endometriosis|chlamydia|thrush|yeast|herpes|syphilis|gonorrh\w+|trichomon\w*|vaginosis|"
    r"pregnan\w*|miscarriage|ectopic|preeclampsia|depress\w*|anxiety|uti|sti|std|bacterial|viral|"
    r"menopause|thyroid|infertil\w*|allerg\w*|disease|condition|disorder|syndrome|sindrom\w*|bolest\w*)"
)
_DIAGNOSIS_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:da\s+li|dal|jel|je\s+li)\s+(?:ja\s+)?(?:mozda\s+)?imam\b"),
    re.compile(r"\bimam\s+li\b"),
    re.compile(rf"\b(?:da\s+li|dal|jel|je\s+li)\s+(?:je\s+)?(?:to|ovo)\s+(?:mozda\s+)?(?:\w+\s+){{0,2}}?{_CONDITION}\b"),
    re.compile(r"\b(?:da\s+li|dal|jel|je\s+li|jesam\s+li|mogu\s+li|moguce\s+da)\s+(?:ja\s+)?(?:sam\s+|biti\s+|budem\s+)?(?:mozda\s+)?trudna\b"),
    re.compile(r"\b(?:sta|sto)\s+(?:mi|mu|joj|ti)\s+je\b"),
    re.compile(r"\b(?:sta|sto)\s+(?:je\s+)?(?:mi|mu|joj)\s+(?:ovo|to)\b"),
    re.compile(r"\b(?:mislim|sumnjam|bojim\s+se|plasim\s+se)\s+da\s+(?:imam|sam\s+trudna)\b"),
    re.compile(r"\bdijagnoz\w*\b"),
    re.compile(r"\b(?:do|could|might|can|may)\s+i\s+(?:possibly\s+|maybe\s+)?(?:have|be\s+having|be)\b"),
    re.compile(rf"\bis\s+(?:this|it|that)\s+(?:maybe\s+|possibly\s+)?(?:a\s+|an\s+)?{_CONDITION}\b"),
    re.compile(r"\bwhat(?:\s*s|\s+is)\s+wrong\s+with\s+(?:me|my|him|her)\b"),
    re.compile(r"\bdiagnos\w*\b"),
    re.compile(r"\bi\s+think\s+i\s+(?:have|am\s+pregnant|might\s+be)\b"),
    re.compile(r"\bam\s+i\s+(?:pregnant|sick|infected|anaemic|anemic)\b"),
    re.compile(r"\bdo\s+you\s+think\s+(?:i|it|this)\b"),
    re.compile(r"\b(?:ili|mozda|možda)\s+(?:je\s+)?(?:da\s+)?imam\b"),
    re.compile(r"\bwhat\s+(?:is|could|might|can)\s+(?:it|this|that)(?:\s+be)?$"),
    re.compile(rf"\b(?:je\s+li|jel|da\s+li\s+je)\s+(?:to|ovo)\s+normalno\s+ili\s+(?:je\s+)?(?:\w+\s+){{0,2}}?{_CONDITION}\b"),
)

# --- test interpretation --------------------------------------------------------------------
_ANALYTE = (
    r"(?:hemoglobin\w*|haemoglobin\w*|hgb|hb\b|leukocit\w*|eritrocit\w*|trombocit\w*|tsh|ft4|ft3|hcg|bhcg|"
    r"beta\s+hcg|prolaktin\w*|prolactin\w*|progesteron\w*|progesterone|estradiol\w*|fsh|lh\b|amh|"
    r"glukoz\w*|glucose|insulin\w*|feritin\w*|ferritin|crl|bpd|nuhaln\w*|nuchal|papa\s+test\w*|pap\s+(?:test|smear)|"
    r"papanikolau|hba1c|crp|sedimentacij\w*|holesterol\w*|cholesterol|bilirubin\w*|kreatinin\w*|creatinine|"
    r"leukocyte\w*|platelet\w*|white\s+cells?|red\s+cells?|vitamin\s+d\b|secer\s+u\s+krvi|blood\s+sugar)"
)
_GENERIC_TEST = (
    r"(?:bris\w*|swab\w*|urin\w*|urine|nalaz\w*|rezultat\w*|result\w*|analiz\w*|lab\w*|ultrazvuk\w*|ultrasound|"
    r"scan|ctg|test\w*|reading\w*|level\w*|vrijednost\w*|vrednost\w*)"
)
# First-person result context: the user reports their own result.
_RESULT_CONTEXT = (
    r"(?:\bmi\s+je\b|\bmi\s+su\b|\bmoj\w*\b|\bdobila\s+sam\b|\bdobio\s+sam\b|\buradila\s+sam\b|\buradio\s+sam\b|"
    r"\bizvadila\s+sam\b|\bvadila\s+sam\b|\bnalaz\s+mi\b|\bnalazi\s+mi\b|\brezultat\s+mi\b|\bstig(?:ao|la|li)\s+mi\b|"
    r"\bmy\b|\bcame\s+back\b|\bgot\s+(?:my|the|back)\b|\bi\s+had\s+(?:a|my|the)\b|\bi\s+did\s+(?:a|my|the)\b|\bthey\s+found\b|\bnasli\s+su\s+mi\b)"
)
_LAB_VALUE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mmol|mg\s?dl|g\s?l|iu|miu|mu|ng\s?ml|pg\s?ml|nmol|umol|miu\s?ml)\b"
)
_ANALYTE_RE = re.compile(rf"\b{_ANALYTE}\b")
_GENERIC_TEST_RE = re.compile(rf"\b{_GENERIC_TEST}\b")
_RESULT_CONTEXT_RE = re.compile(_RESULT_CONTEXT)
_ANALYTE_WITH_NUMBER_RE = re.compile(
    rf"\b{_ANALYTE}\b(?:\s+\w+){{0,2}}?\s+(?:mi\s+je\s+|je\s+|is\s+|su\s+|are\s+|od\s+|of\s+|at\s+)?\d+(?:[.,]\d+)?\b"
)
_SCALE_RE = re.compile(r"\b(?:ascus|lsil|hsil|cin\s?[123]|pap\s?[1-5]|papa\s?[1-5]|\+{2,}|pozitiv\w*|positiv\w*)\b")
_MEANING_RE = re.compile(r"\b(?:sta\s+(?:to\s+)?znaci|what\s+does\s+(?:it|this|that)\s+mean|is\s+(?:that|this|it)\s+(?:bad|ok|okay|normal|good|high|low)|da\s+li\s+je\s+to\s+(?:lose|dobro|ok|normalno|visoko|nisko))\b")

# --- manipulation ----------------------------------------------------------------------------
_MANIPULATION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:ignori\w*|zanemari\w*|zaboravi\w*|preskoci\w*|odbaci\w*)\b(?:\s+\w+){0,6}?\s+(?:pravil\w*|instrukcij\w*|uputstv\w*|uput\w*|ogranicenj\w*|smjernic\w*|smernic\w*|program\w*)\b"),
    re.compile(r"\b(?:ignore|forget|disregard|bypass|override|skip|drop)\b(?:\s+\w+){0,6}?\s+(?:rules?|instructions?|guidelines?|restrictions?|limitations?|limits?|safety|guardrails?|programming|training|policy|policies|previous|prior|above)\b"),
    re.compile(r"\b(?:pretvaraj|pretvaraj\s+se|glumi|zamisli|ponasaj\s+se|zamislimo)\s+(?:se\s+)?(?:kao\s+)?da\s+si\b"),
    re.compile(r"\b(?:ti\s+si|od\s+sada\s+si|od\s+sad\s+si|sada\s+si|sad\s+si)\s+(?:sada\s+|sad\s+|od\s+sada\s+)?(?:moj\w*\s+)?(?:ljekar\w*|lekar\w*|doktor\w*|ginekolog\w*|lijecni\w*|farmaceut\w*|sestra|babica)\b"),
    re.compile(r"\b(?:igrajmo\s+se|hajde\s+da\s+se\s+igramo|igramo\s+se|igra\s+uloga|uloga)\b"),
    re.compile(r"\brole\s?play\w*\b"),
    re.compile(r"\bpretend\s+(?:to\s+be|you\s+are|you're|that)\b"),
    re.compile(r"\bact\s+as\s+(?:a\s+|an\s+|my\s+)?\b"),
    re.compile(r"\byou\s+are\s+now\b"),
    re.compile(r"\bfrom\s+now\s+on\s+you\b"),
    re.compile(r"\bas\s+my\s+(?:doctor|gynae?cologist|pharmacist|nurse|midwife)\b"),
    re.compile(r"\b(?:jailbreak\w*|dan\s+mode|developer\s+mode|god\s+mode|system\s+prompt|sistemsk\w+\s+prompt|prompt)\b"),
    re.compile(r"\bbez\s+(?:ikakvih\s+|svojih\s+|tvojih\s+)?(?:ogranicenj\w*|pravila|filter\w*|cenzur\w*)\b"),
    re.compile(r"\bwithout\s+(?:any\s+|your\s+)?(?:restrictions?|limits?|limitations?|rules|filters?)\b"),
    re.compile(r"\bno\s+(?:restrictions?|limits?|filters?|rules)\b"),
    re.compile(r"\b(?:ovo\s+je|this\s+is)\s+(?:a\s+)?test\b(?:\s+\w+){0,3}?\s+(?:od|from|by)\s+(?:tvojih\s+|your\s+)?(?:programer\w*|developer\w*|creator\w*|tvorac\w*|autor\w*)\b"),
    re.compile(r"\bza\s+potrebe\s+testa\b"),
    re.compile(r"\b(?:rek(?:la|lo|ao|li|le)|kaze|kazu|kazala|kazao|dozvoli\w*|dozvolje\w*)\s+(?:je\s+|su\s+)?(?:mi\s+)?da\s+(?:mi\s+)?(?:smijes|smes|mozes|moze|smije|sme)\b"),
    re.compile(r"\b(?:said|says|allowed|permitted)\s+(?:that\s+)?(?:you\s+)?(?:can|may|are\s+allowed\s+to)\s+(?:tell|give)\s+me\b"),
    re.compile(r"\b(?:moras|mora\w*|obavezn\w*)\s+(?:mi\s+)?(?:reci|dati|odgovoriti)\b"),
    re.compile(r"\byou\s+(?:must|have\s+to)\s+(?:tell|answer|give)\b"),
    re.compile(r"\b(?:odgovori|odgovor|answer|reply|respond)\s+(?:samo\s+|only\s+)?(?:brojem|jednom\s+rijec\w*|jednom\s+rec\w*|with\s+(?:a\s+|one\s+)?(?:number|word)|in\s+one\s+word|only\s+with)\b"),
    re.compile(r"\bbez\s+(?:upozorenja|objasnjenja|disclaimer\w*|uvoda|napomen\w*)\b"),
    re.compile(r"\b(?:no|without|skip\s+the|drop\s+the)\s+(?:a\s+|any\s+|the\s+)?(?:disclaimer\w*|warning\w*|caveat\w*|lecture)\b"),
    re.compile(r"\b(?:this\s+is|ovo\s+je)\s+(?:a\s+|an\s+)?(?:developer|dev|programer\w*|qa|internal|interni)\s+test\b"),
    re.compile(r"\bfor\s+(?:the|this)\s+test\b"),
)


def _first(patterns: tuple[re.Pattern[str], ...], text: str) -> int | None:
    for index, rx in enumerate(patterns):
        if rx.search(text):
            return index
    return None


def asks_for_dose(text: str) -> bool:
    """True when the question asks for a dose, a quantity of a medicine, or which medicine to take."""
    normalised = normalize_text(text)
    return mentions_medication_dose(text) or _first(_DOSE_RES, normalised) is not None


def asks_for_diagnosis(text: str) -> bool:
    return _first(_DIAGNOSIS_RES, normalize_text(text)) is not None


def asks_for_test_interpretation(text: str) -> bool:
    """True when the user asks what THEIR result means.

    A named analyte with a value ("hemoglobin mi je 105", "TSH 4.8", "Papa test ASCUS") is
    enough on its own; a generic test word ("nalaz", "ultrazvuk", "test") needs a first-person
    result context ("dobila sam nalaz ...", "my results came back ..."). "Šta je papa test" or
    "kada se radi prvi ultrazvuk" stay in scope.
    """
    normalised = normalize_text(text)
    analyte = _ANALYTE_RE.search(normalised) is not None
    generic = _GENERIC_TEST_RE.search(normalised) is not None
    if not (analyte or generic):
        return False
    if analyte and (
        _ANALYTE_WITH_NUMBER_RE.search(normalised)
        or _LAB_VALUE_RE.search(normalised)
        or _SCALE_RE.search(normalised)
        or _RESULT_CONTEXT_RE.search(normalised)
    ):
        return True
    if generic and _RESULT_CONTEXT_RE.search(normalised) and (
        _LAB_VALUE_RE.search(normalised) or _SCALE_RE.search(normalised) or _MEANING_RE.search(normalised)
        or re.search(r"\b(?:pokazuj\w*|pokazal\w*|pise|shows?|showed|says)\b", normalised)
    ):
        return True
    return False


def is_manipulation(text: str) -> bool:
    return _first(_MANIPULATION_RES, normalize_text(text)) is not None


def classify_scope(text: str) -> ScopeResult:
    """Classify a question; manipulation first (it often wraps another request), then dose,
    diagnosis and test interpretation."""
    normalised = normalize_text(text)
    hit = _first(_MANIPULATION_RES, normalised)
    if hit is not None:
        return ScopeResult("manipulation", f"manipulation:{hit}")
    if mentions_medication_dose(text):
        return ScopeResult("dose", "dose:units")
    hit = _first(_DOSE_RES, normalised)
    if hit is not None:
        return ScopeResult("dose", f"dose:{hit}")
    if asks_for_test_interpretation(text):
        return ScopeResult("test_interpretation", "test_interpretation")
    hit = _first(_DIAGNOSIS_RES, normalised)
    if hit is not None:
        return ScopeResult("diagnosis", f"diagnosis:{hit}")
    return ScopeResult(None)
