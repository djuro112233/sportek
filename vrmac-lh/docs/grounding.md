# Grounded answers or refusal

> Innovation claim #2. Two controls, both real: a **human approval** of every entry before publication,
> and a **per-answer support check** that removes any sentence not attributable to a cited approved
> passage. If nothing survives, the answer is withheld and the refusal is logged.

## The pipeline

1. **Language.** Function words decide (`detect_lang` in `services/rag.py`); diacritics only break a tie,
   and only in a lower-case word — an English question naming Lovćen or Njegoš stays English.
2. **Retrieval.** The question is embedded and matched against `entry_chunks` by pgvector cosine
   distance **through the visitor database role**, so row-level security limits the search to approved
   entries, and `approved_only` filters again on top. Chunks in the question's language rank slightly
   higher; the other language is not excluded, so a Montenegrin question can still cite the English text
   of the same approved entry.
3. **Confidence gate.** The chunk that would be cited must satisfy `similarity ≥ RAG_MIN_SIMILARITY`
   **and** `coverage ≥ RAG_MIN_COVERAGE`. Coverage is the IDF-weighted share of the question's
   content-word stems present in the chunk, so ubiquitous words (Gornja, Lastva, godine) count little
   and specific ones (Stoliv, 1687, ferry) count a lot.
4. **Answer.** With a model configured, it must answer only from the numbered sources, cite them as
   `[n]`, and reply exactly `NOT_IN_SOURCES` when they do not contain the answer (that reply becomes a
   refusal). Without a model — `LLM_PROVIDER=none`, an unreachable provider, or an exhausted spend cap —
   the answer is **extractive**: the one or two most relevant sentences of the cited passages.
5. **Support check.** Every sentence is checked against the cited passages
   (`providers/support.py`). Unsupported sentences are dropped; the verdicts travel back in the
   response and into the review record. If every sentence is dropped, the answer is withheld with
   `unsupported_answer`.
6. **Events.** `answer_served` or `answer_withheld`, pseudonymised, carrying the question's length and a
   hash — never its text. An unlinked `answer_records` row keeps the question and answer for the monthly
   human review.

## Thresholds and how they were calibrated

Measured over the two 30-question sets with the offline providers (hash embeddings, no model, lexical
support check). The gap between the two classes is wide, which is why the defaults are not tuned per
question:

| Signal | Answerable (n=40) | Unanswerable (n=20) | Threshold |
|---|---|---|---|
| top similarity | min 0.423, median 0.622, max 0.905 | min 0.046, median 0.118, max 0.493 | 0.35 |
| coverage (IDF-weighted) | min 0.390, median 1.000 | min 0.000, median 0.142, max 0.442 | 0.34 |
| confidence | min 0.481, median 0.779 | min 0.023, median 0.170, max 0.391 | — |

The support check's `SUPPORT_MIN_SCORE` is 0.75, and the lexical implementation additionally rejects a
sentence outright when any number in it is missing from the passage — an invented year or price can
never pass.

## Result

| | Montenegrin | English |
|---|---|---|
| answerable questions answered with an approved citation | 20 / 20 | 20 / 20 |
| unanswerable questions withheld | 10 / 10 | 10 / 10 |

The brief's floor is 90 % of the answerable set and 100 % of the unanswerable set. Regenerate with
`make grounding` or `pytest tests/test_grounding.py`; the full table lands in `docs/test-results/`.

The unanswerable set deliberately mixes three kinds of question: facts that exist **only in
non-approved entries** (the invented golden bell of 1687, the old school's 41 pupils, the Roman villa),
facts about **Gornji Stoliv**, whose entry is seeded as unverified and therefore unpublishable, and
plain off-topic questions (ferry timetables, hotel prices, tomorrow's weather).

## Relevance versus attribution — a known limitation

The support check answers "is this sentence backed by the cited passage?", not "does this passage answer
the question?". In the offline extractive mode the two can come apart: withdraw every approved entry
that mentions St Vitus and ask about its century, and the assistant may answer from the entry about the
*church of St Mary* — a correctly cited, correctly attributed, but off-target answer.

Two things bound the problem, and one does not fix it:

* With a model configured, this case is refused: the system prompt requires `NOT_IN_SOURCES` when the
  sources do not contain the answer, and that is the configuration used for the pilot.
* A relevance gate requiring the question's rarest term to appear in the passage was implemented and
  **measured, then rejected**: the rarest stem of a question is usually a framing word the descriptive
  corpus never uses ("dana", "nalazi", "day", "year"), so the rule refused 11 of 40 answerable questions
  while the withholding rate stayed at 100 %. The diagnostic remains in the response's `debug`
  (`decisive_stems`) so the decision can be revisited with a real embedding model.

The guarantee the brief states is unaffected and is tested: only approved entries are retrievable, and
an entry that leaves `approved` is never cited again (`tests/test_grounding.py`).

## Response cache

Exact hits key on a hash of the normalised question and the language; semantic hits on cosine similarity
≥ `CACHE_SEMANTIC_MIN_SIMILARITY` (0.92). Every cached answer records the version of each entry it
cites, and a hit is served only if every one of those entries is still approved and still at that
version; otherwise the row is marked invalidated with the reason. When the monthly spend cap is reached,
a valid cache hit is still served — with its citations — and everything else becomes a polite pause.

## Adding a launch language

Add `seed_data/grounding_questions.<lang>.json` with its own 20 answerable and 10 unanswerable
questions and independently prepared expected answers, translate the refusal messages, and only enable
the language once that set passes. The per-language rates are reported separately for exactly this
reason.
