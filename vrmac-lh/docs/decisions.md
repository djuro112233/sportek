# Decisions and assumptions

1. **Location in the repository.** The `sportek` repository already contains an unrelated project at its root, so the
   prototype lives in `vrmac-lh/` with its own README, compose stack and CI workflow (`.github/workflows/vrmac-lh-ci.yml`,
   path-filtered).
2. **Reference documents.** `SIP_Draft_Vrmac_Living_Heritage.pdf` and `VRMAC_LH_Prototype.html` were not in the repository
   or reachable from the build environment. Screens, copy and the architecture diagram follow the brief; they should be
   aligned with the SIP Draft (§2.2 architecture, §2.3 workflows, §11 KPIs) and the HTML mock-up before the pitch.
3. **Expeditio 2015 citation.** The brief asks to cite the Expeditio (2015) studies by title; the titles were not available,
   so the source string carries a visible placeholder to complete.
4. **Local language code.** Montenegrin is `cnr` (ISO 639-3); the UI uses `cnr`/`en`. Whisper has no Montenegrin model
   code, so `STT_LANGUAGE=hr` is used for Latin-script output (configurable).
5. **Small models.** Defaults are `qwen2.5:1.5b` (LLM) and `paraphrase-multilingual` (embeddings) via Ollama, and
   faster-whisper `small` (int8) — all CPU-only and sized for 2 vCPU / 4 GB. Any OpenAI-compatible API can replace the
   LLM (`LLM_PROVIDER=openai`) and any Whisper-compatible API the STT (`STT_PROVIDER=api`).
6. **Offline test mode.** CI and the sandbox cannot download models, so the tests run with `EMBEDDINGS_PROVIDER=hash`
   (deterministic lexical hashing), `LLM_PROVIDER=none` (extractive answers) and `STT_PROVIDER=fixture`. The refusal
   logic, citations, gate and KPI code paths are identical in both modes; only the model quality differs.
7. **Validation gate in the data layer.** Implemented with a second PostgreSQL role restricted by row-level security in
   addition to explicit query filters and CHECK constraints (see `docs/architecture.md`).
8. **Synthetic event history.** The KPI dashboard needs enough events to show k≥5 suppression at work, so the seed
   loads a deterministic synthetic history (flagged `synthetic: true`) for 12 fictional hosts and ~45 anonymous visitor
   sessions. All KPI values are computed from those rows; none is typed in.
9. **Extra event types.** `item_rejected` and `visit_recorded` complement the eleven events named in the brief
   (the heat map of measured visits needs a visit event).
