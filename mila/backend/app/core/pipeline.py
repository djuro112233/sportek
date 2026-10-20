"""The answer pipeline: red-flag router → retrieval → generation → verifier → gate → response.

:class:`AskPipeline.ask` is the only code path that turns a question into an
:class:`AskResponse`. It follows the diagram in ``docs/architecture.md`` in this order:

1. resolve language, script and region (the request overrides the session);
2. red-flag check; a flag ends the request with a referral and no generated text;
3. hybrid retrieval over the knowledge base (``settings.retrieval_top_k`` chunks);
4. constrained generation with ``[Sn]`` markers;
5. sentence-level verification against the cited chunks (``S1`` is ``chunks[0]``);
6. the validation gate; ``decision.kept`` is the only text that may be shown and nothing is
   shown when the gate withholds;
7. referral, disclaimer, optional speech, then an aggregate-only event, the gate record linked
   to it and, with the separate consent, the saved question.

The pipeline fails closed: any exception in the router, retrieval, generation, verification
or the gate ends in a withheld response with gate reason ``pipeline_error`` and an ``ask``
event with outcome ``error`` that carries the exception class name only. Nothing here logs
the question, the chunks or the answer; the logging filter from ``app.core.privacy`` masks
what a library message might still carry.
"""

from __future__ import annotations

import logging
import math
import time

from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.core.container import Providers, router_for
from app.core.events import classify_topic, log_event
from app.core.gate import GATE_VERSION, ValidationGate, record_decision
from app.core.generation import Generator
from app.core.i18n import coerce_lang, render, t
from app.core.referral import ReferralService, ensure_referral_points
from app.core.relevance import question_relevance, sentence_relevance
from app.core.retrieval import Retriever
from app.core.scope import SCOPE_MESSAGE_KEYS, SCOPE_REASONS, asks_for_dose, classify_scope
from app.core.types import (
    AnswerSentence,
    AskRequest,
    AskResponse,
    Citation,
    GateDecision,
    RedFlagResult,
    Referral,
    RetrievedChunk,
)
from app.core.verifier import SupportJudge, Verifier, get_judge
from app.kb.embed import Embedder, get_embedder
from app.models import SavedQuestion, Session
from app.services.llm import LLMClient, get_llm
from app.services.tts import TTS, clean_for_speech, get_tts

log = logging.getLogger("mila.pipeline")

REASON_PIPELINE_ERROR = "pipeline_error"

__all__ = ["AskPipeline", "asks_for_dose", "public_gate"]

UNREVIEWED_STATUS = "public_unreviewed"


class PipelineError(RuntimeError):
    """An exception raised by one pipeline stage, tagged with the stage name (never user text)."""

    def __init__(self, stage: str, cause: BaseException) -> None:
        super().__init__(f"{stage} failed: {type(cause).__name__}")
        self.stage = stage
        self.cause = cause


def elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started`` (``time.perf_counter``), never below 1."""
    return max(1, math.ceil((time.perf_counter() - started) * 1000))


def citation_index(marker: str) -> int | None:
    """``"S3"`` → ``2``; ``None`` for anything that is not a well-formed marker."""
    digits = marker[1:] if marker[:1] in ("S", "s") else ""
    return int(digits) - 1 if digits.isdigit() and int(digits) > 0 else None


def cited_chunks(
    sentences: list[AnswerSentence], chunks: list[RetrievedChunk]
) -> list[tuple[str, RetrievedChunk]]:
    """``(marker, chunk)`` pairs cited by the sentences, each chunk once, in marker order."""
    found: dict[int, str] = {}
    for sentence in sentences:
        for marker in sentence.citations:
            index = citation_index(marker)
            if index is not None and 0 <= index < len(chunks) and index not in found:
                found[index] = f"S{index + 1}"
    return [(found[index], chunks[index]) for index in sorted(found)]


def build_citations(kept: list[AnswerSentence], chunks: list[RetrievedChunk]) -> list[Citation]:
    """Citations for the chunks the kept sentences actually cite. Titles are never transliterated."""
    return [
        Citation(
            marker=marker,
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            source_title=chunk.source_title,
            section=chunk.heading_path,
            version=chunk.source_version,
            date=chunk.published_on,
            page=chunk.page,
            review_status=chunk.review_status,
            lang=chunk.lang,
        )
        for marker, chunk in cited_chunks(kept, chunks)
    ]


def public_gate(decision: GateDecision | None) -> GateDecision | None:
    """The gate decision as it may leave the server: removed sentences lose their text, and so
    do the kept ones when the answer is withheld. Reasons, scores and counts stay."""
    if decision is None:
        return None
    blank = {"text": ""}
    kept = (
        decision.kept
        if decision.status == "approved"
        else [s.model_copy(update=blank) for s in decision.kept]
    )
    return decision.model_copy(
        update={"kept": kept, "removed": [s.model_copy(update=blank) for s in decision.removed]}
    )


class AskPipeline:
    """Compose the providers into the answer flow for one request.

    Accepts a :class:`Providers` container (what the API passes) or the individual providers
    as keyword arguments (what ``scripts/measure.py`` passes); missing ones are built from
    the settings. ``tts`` is built on demand the first time audio is requested.
    """

    def __init__(
        self,
        settings: Settings,
        db: DbSession,
        providers: Providers | None = None,
        *,
        llm: LLMClient | None = None,
        embedder: Embedder | None = None,
        judge: SupportJudge | None = None,
        redflags=None,
        tts: TTS | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        if providers is None:
            llm = llm if llm is not None else get_llm(settings)
            providers = Providers(
                llm=llm,
                embedder=embedder if embedder is not None else get_embedder(settings),
                judge=judge if judge is not None else get_judge(settings, llm),
                redflags=redflags if redflags is not None else router_for(settings),
                tts=tts,
            )
        self.providers = providers
        self.retriever = Retriever(db, providers.embedder, settings)
        self.generator = Generator(providers.llm)
        self.verifier = Verifier(providers.judge, threshold=settings.verifier_support_threshold)
        self.gate = ValidationGate.from_settings(settings)
        self.referrals = ReferralService(db)
        ensure_referral_points(db)

    # --- entry point ------------------------------------------------------------------------
    def ask(self, req: AskRequest, session: Session) -> AskResponse:
        started = time.perf_counter()
        text = req.text.strip()
        lang = coerce_lang(req.lang or session.lang)
        script = req.script if "script" in req.model_fields_set else (session.script or "latin")
        region = (req.region or session.region or self.settings.default_region).strip().upper()
        topic = classify_topic(text)
        ctx = _Context(
            req=req, session=session, text=text, lang=lang, script=script, region=region, topic=topic
        )

        try:
            flag = self._stage(
                "redflag", lambda: self.providers.redflags.check(text, lang=lang, is_minor=session.is_minor)
            )
            if flag.flagged:
                return self._finish_redflag(ctx, flag, started)
            scope = self._stage("scope", lambda: classify_scope(text))
            if scope.kind is not None:
                decision = GateDecision(
                    status="withheld", gate_version=GATE_VERSION, reasons=[SCOPE_REASONS[scope.kind]]
                )
                return self._finish_decided(
                    ctx, [], decision, False, started, message_key=SCOPE_MESSAGE_KEYS[scope.kind]
                )
            chunks = self._stage("retrieval", lambda: self._retrieve(ctx))
            raw = self._stage(
                "generation",
                lambda: self.generator.generate(text, chunks, lang, is_minor=bool(session.is_minor)),
            )
            sentences = self._stage("verification", lambda: self.verifier.verify(raw.text, chunks))
            relevance, per_sentence = self._stage(
                "relevance", lambda: self._relevance(ctx, sentences, chunks)
            )
            decision = self._stage(
                "gate",
                lambda: self.gate.decide(
                    sentences, chunks, relevance=relevance, sentence_relevance=per_sentence
                ),
            )
        except PipelineError as failure:
            return self._finish_failed(ctx, failure, started)
        return self._finish_decided(ctx, chunks, decision, raw.translated, started)

    # --- stages -----------------------------------------------------------------------------
    @staticmethod
    def _stage(name: str, call):
        try:
            return call()
        except Exception as exc:  # every failure must fail closed
            raise PipelineError(name, exc) from exc

    def _relevance(
        self, ctx: _Context, sentences: list[AnswerSentence], chunks: list[RetrievedChunk]
    ) -> tuple[float | None, dict[int, float]]:
        """Answer-level and per-sentence question coverage (see ``app.core.relevance``).

        Fails closed: a question without content words scores 0.0. When no cited chunk shares
        the question's language family the lexical score is meaningless, so the LLM judge is
        asked instead when one is configured; without it the cross-lingual answer is withheld.
        """
        if not any(s.supported for s in sentences):
            return None, {}
        idf = self.retriever.stem_idf()
        penalty = self.settings.relevance_unknown_term_penalty
        per_sentence = sentence_relevance(ctx.text, sentences, chunks, idf, unknown_term_penalty=penalty)
        floor = self.settings.gate_min_sentence_relevance
        survivors = [
            s for i, s in enumerate(sentences) if i not in per_sentence or per_sentence[i] >= floor
        ]
        answer = question_relevance(
            ctx.text, ctx.lang, survivors, chunks, idf, unknown_term_penalty=penalty
        )
        if answer is not None:
            # An LLM judge, when configured, decides relevance (it understands paraphrases and
            # other languages); the lexical score remains the fallback and the only check when
            # the judge is lexical. Without a judge, a cross-lingual answer fails closed.
            judged = self._llm_relevance(ctx.text, sentences, chunks)
            if judged is not None:
                answer = judged
                per_sentence = {} if judged >= self.settings.gate_min_relevance else per_sentence
        return answer, per_sentence

    def _llm_relevance(
        self, question: str, sentences: list[AnswerSentence], chunks: list[RetrievedChunk]
    ) -> float | None:
        judge = self.providers.judge
        relevance_fn = getattr(judge, "relevance", None)
        if relevance_fn is None:
            return None
        cited: list[str] = []
        for sentence in sentences:
            if not sentence.supported or sentence.flagged_medication:
                continue
            for marker in sentence.citations:
                digits = marker[1:]
                if digits.isdigit() and 0 < int(digits) <= len(chunks):
                    text = chunks[int(digits) - 1].text
                    if text not in cited:
                        cited.append(text)
        if not cited:
            return None
        return float(relevance_fn(question, "\n\n".join(cited)))

    def _retrieve(self, ctx: _Context) -> list[RetrievedChunk]:
        topic = ctx.topic if ctx.topic != "other" else None
        return self.retriever.search(
            ctx.text, lang=ctx.lang, top_k=self.settings.retrieval_top_k, topic=topic
        )

    def _referral(self, ctx: _Context, category: str | None) -> Referral:
        return self.referrals.for_context(
            region=ctx.region,
            lang=ctx.lang,
            script=ctx.script,
            category=category,
            is_minor=ctx.session.is_minor,
        )

    # --- outcomes ---------------------------------------------------------------------------
    def _finish_redflag(self, ctx: _Context, flag: RedFlagResult, started: float) -> AskResponse:
        referral = self._referral(ctx, flag.category)
        response = AskResponse(
            outcome="redflag",
            session_id=ctx.session.id,
            lang=ctx.lang,
            script=ctx.script,
            topic_class=ctx.topic,
            message=referral.message,
            referral=referral,
            disclaimer_short=t("disclaimer_short", ctx.lang, ctx.script),
            minor_note=t("minor_note", ctx.lang, ctx.script) if ctx.session.is_minor else "",
            redflag_category=flag.category,
        )
        if ctx.req.want_audio:
            response.audio_url = self._speak(response.message, ctx)
        response.latency_ms = elapsed_ms(started)
        log_event(
            self.db,
            type="redflag",
            session_id=ctx.session.id,
            lang=ctx.lang,
            topic_class=ctx.topic,
            outcome="redflag",
            latency_ms=response.latency_ms,
            redflag_category=flag.category or "",
            input_mode=ctx.req.input_mode,
            payload={
                "source": flag.source,
                "child_protection": flag.child_protection,
                "emergency": referral.emergency,
                "want_audio": ctx.req.want_audio,
            },
        )
        self._save_question(ctx, "redflag")
        return response

    def _finish_decided(
        self,
        ctx: _Context,
        chunks: list[RetrievedChunk],
        decision: GateDecision,
        translated: bool,
        started: float,
        message_key: str = "withheld",
    ) -> AskResponse:
        approved = decision.status == "approved"
        referral = self._referral(ctx, None)
        response = AskResponse(
            outcome="answered" if approved else "withheld",
            session_id=ctx.session.id,
            lang=ctx.lang,
            script=ctx.script,
            topic_class=ctx.topic,
            confidence=decision.confidence,
            support_ratio=decision.support_ratio,
            referral=referral,
            disclaimer_short=t("disclaimer_short", ctx.lang, ctx.script),
            minor_note=t("minor_note", ctx.lang, ctx.script) if ctx.session.is_minor else "",
            gate=decision,
        )
        if approved:
            kept = decision.kept
            response.sentences = [
                s.model_copy(update={"text": render(s.text, ctx.lang, ctx.script)}) for s in kept
            ]
            response.citations = build_citations(kept, chunks)
            response.translated = translated
            response.demo_unreviewed_sources = any(
                chunk.review_status == UNREVIEWED_STATUS for _, chunk in cited_chunks(kept, chunks)
            )
            if translated:
                response.message = t("translated_note", ctx.lang, ctx.script)
            if ctx.req.want_audio:
                response.audio_url = self._speak(clean_for_speech(" ".join(s.text for s in kept)), ctx)
        else:
            response.message = t(message_key, ctx.lang, ctx.script)
        response.latency_ms = elapsed_ms(started)

        event = log_event(
            self.db,
            type="ask",
            session_id=ctx.session.id,
            lang=ctx.lang,
            topic_class=ctx.topic,
            outcome=response.outcome,
            latency_ms=response.latency_ms,
            support_ratio=decision.support_ratio if approved else None,
            input_mode=ctx.req.input_mode,
            payload={
                "n_chunks": len(chunks),
                "n_sentences_in": len(decision.kept) + len(decision.removed),
                "n_kept": len(decision.kept),
                "translated": bool(translated and approved),
                "want_audio": ctx.req.want_audio,
                "gate_status": decision.status,
                "gate_reasons": list(decision.reasons),
                "relevance": decision.relevance,
            },
        )
        record_decision(self.db, decision, event_id=event.id)
        self._save_question(ctx, response.outcome)
        return response

    def _finish_failed(self, ctx: _Context, failure: PipelineError, started: float) -> AskResponse:
        """Fail closed: no answer text, a general referral, and an error event (class name only)."""
        log.exception("pipeline stage %s failed", failure.stage, exc_info=failure.cause)
        decision = GateDecision(status="withheld", gate_version=GATE_VERSION, reasons=[REASON_PIPELINE_ERROR])
        try:
            referral: Referral | None = self._referral(ctx, None)
        except Exception:  # the referral must not turn an error into a crash
            log.exception("referral lookup failed after a pipeline error")
            referral = None
        response = AskResponse(
            outcome="withheld",
            session_id=ctx.session.id,
            lang=ctx.lang,
            script=ctx.script,
            topic_class=ctx.topic,
            message=t("withheld", ctx.lang, ctx.script),
            referral=referral,
            disclaimer_short=t("disclaimer_short", ctx.lang, ctx.script),
            gate=decision,
            latency_ms=elapsed_ms(started),
        )
        try:
            event = log_event(
                self.db,
                type="ask",
                session_id=ctx.session.id,
                lang=ctx.lang,
                topic_class=ctx.topic,
                outcome="error",
                latency_ms=response.latency_ms,
                input_mode=ctx.req.input_mode,
                payload={"error": type(failure.cause).__name__, "stage": failure.stage},
            )
            record_decision(self.db, decision, event_id=event.id)
            self._save_question(ctx, "withheld")
        except Exception:  # bookkeeping must not hide the withheld response
            log.exception("could not record the pipeline error")
            self.db.rollback()
        return response

    # --- side effects -----------------------------------------------------------------------
    def _speak(self, spoken: str, ctx: _Context) -> str | None:
        """Synthesise ``spoken`` and return a one-time audio URL; ``None`` when speech fails."""
        from app.api.speak import audio_url, register_audio  # the store lives with its route

        spoken = render(spoken, ctx.lang, ctx.script).strip()
        if not spoken:
            return None
        try:
            tts = self.providers.tts
            if tts is None:
                tts = self.providers.tts = get_tts(self.settings)
            wav = tts.synthesize(spoken, ctx.lang, low_bandwidth=ctx.req.low_bandwidth)
            return audio_url(register_audio(wav, session_id=ctx.session.id))
        except Exception:  # the text answer stands even when speech fails
            log.exception("speech synthesis failed")
            return None

    def _save_question(self, ctx: _Context, outcome: str) -> None:
        """Store the question only with the separate consent; a storage failure never fails the
        response and never logs the text (the exception class name only)."""
        if not ctx.session.consent_save_questions:
            return
        try:
            self.db.add(
                SavedQuestion(session_id=ctx.session.id, text=ctx.req.text, lang=ctx.lang, outcome=outcome)
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - fail open for storage, closed for privacy
            self.db.rollback()
            log.warning("saved question not stored: %s", type(exc).__name__)


class _Context:
    """Per-request values resolved once; never logged."""

    __slots__ = ("req", "session", "text", "lang", "script", "region", "topic")

    def __init__(
        self, *, req: AskRequest, session: Session, text: str, lang: str, script: str, region: str, topic: str
    ) -> None:
        self.req = req
        self.session = session
        self.text = text
        self.lang = lang
        self.script = script
        self.region = region
        self.topic = topic
