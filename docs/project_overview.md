# BushfireReadyGPT Project Overview

## What This Project Is

BushfireReadyGPT is an Australia-focused bushfire preparedness planning MVP. It helps a user produce a structured draft preparedness report from a selected location, audience, scenario, planning focus and review context.

The project is designed for controlled demonstration and pilot discussion with councils, schools and community resilience teams. It is not an operational emergency management platform.

## What Changed From The Original Project

The original open-source project was a wildfire-oriented assistant with legacy United States data, older assistant routes and broader chat-style behaviour.

This version has been rebuilt around an Australian preparedness use case:

- Australia-specific bushfire preparedness theme.
- Form-first report generation instead of a generic chat-first workflow.
- Local Ollama runtime, so no OpenAI API key is required.
- Australia-focused multi-agent analysis pipeline.
- ABS / ASGS-derived geography and community context.
- Official source and licence registers.
- O1 / P2 / R3 / A4 / U0 evidence confidence and provenance labels.
- Human review, sign-off and audit records.
- Markdown, PDF, DOCX and pilot package exports.
- Single self-checking Windows launcher with VSCode and direct PowerShell alternatives.

## Current User Workflow

1. The user opens the Streamlit app.
2. The user loads a pilot example or fills in the report form.
3. The user selects the location, audience, scenario, timeframe and focus areas.
4. The multi-agent pipeline prepares local context, retrieves optional official-knowledge RAG passages and builds planning evidence.
5. The stateless, tool-free local Ollama client generates a formal English draft report.
6. The app appends governance notices, provenance-labelled evidence tables and human review sign-off, then records the canonical Governed Report Check result.
7. A follow-up edit creates a new report ID/version, rebuilds deterministic evidence, reruns the same governed gate and writes a separate audit record.
8. The reviewer checks the evidence trail, data sources, map context and governed checks, then records sign-off; every new version starts as a draft with an empty checklist.
9. Individual draft files remain available for remediation; the governed pilot package requires a fresh passing gate, exact analysis/audit binding and matching review state.
10. A historical-policy audit can be upgraded only through a policy-only `quality.reassessed` event that preserves the exact report, sign-off, status and package context. That event is not a human review, so a later `review.recorded` event is required before pilot-package export.

## Multi-Agent Architecture

| Agent | Role |
| --- | --- |
| Profile Agent | Normalises user inputs and infers scenario context. |
| Australian Data Agent | Selects relevant official sources and records data limitations. |
| Community Vulnerability Agent | Reads local processed community profile data and builds vulnerability notes. |
| Official Knowledge Agent | Queries the verified local hybrid RAG index and returns attributed official passages. |
| Risk Context Agent | Matches Australia / Queensland / Cairns risk rules. |
| Planner Agent | Converts risk context into preparedness priorities. |
| Report Agent | Formats deterministic evidence for the report prompt. |
| Report Quality Agent | Checks report completeness, safety boundaries, checklists and human review status. |

## Data Layer

The active data layer is under `data_australia/`.

It includes:

- Official source metadata.
- Licence register assumptions.
- Risk context rules.
- Processed community profile data.
- ABS ASGS allocation and correspondence reference files.
- Lightweight sample and processed files for local demo use.

Large raw files and geospatial boundary files are ignored by Git and kept as local data assets only.

## What The Project Can Currently Demonstrate

- A working Australia-focused preparedness planning interface.
- A structured form-to-report workflow.
- Multi-agent analysis with visible intermediate evidence.
- Local model generation through Ollama.
- Conventional local RAG using EmbeddingGemma, Qdrant, BM25 and reciprocal-rank fusion.
- Human review and approval boundary.
- Versioned, governed report revisions with approval reset and per-version audit files.
- Evidence tables and audit records.
- Evidence provenance labels that separate official references, processed data, deterministic inference, AI prose and unverified inputs.
- Export to Markdown, PDF, DOCX and pilot package zip.
- Visible source-period, source-age, freshness and geographic-match warnings in the report and Evidence Trail.
- A current Cairns Council sample package, product screenshots and a short demonstration video.
- Commercial gap and project maturity assessment.

## Current Branch Validation (2026-08-24)

- The maintained branch passes `541` automated tests: `540` non-E2E unit/integration/Streamlit tests and one Chromium end-to-end workflow. The measured non-E2E `src` coverage is `86.54%`.
- Explicit map geography is now the effective profile for every downstream agent; conflicting known states fail closed before evidence selection.
- RAG build/inspection/retrieval uses fixed process-then-file locking, token-owned cross-process locks, immutable source snapshots and backup-first publication recovery; release evaluation checks provenance before and after every question or scenario call to detect A-to-B-to-A drift visible across call boundaries, while explicitly not claiming visibility into a model-tag swap wholly inside one HTTP call.
- Session hydration validates a bounded versioned schema, report/review inputs have backend limits, audit ancestry is verified iteratively, and model generation/revision share one repair implementation.
- Local model streaming has a hard wall-clock deadline; unverified U0 values stay in an escaped JSON block rather than deterministic analysis text, and configured YAML source/rule identifiers must be non-empty and unique.
- Evidence Trail views and derived downloads are bound to the frozen report snapshot; PDF/DOCX table parsing is shared and renderer-fingerprinted preview artifacts are cached only inside the current browser session.

These current-branch figures are engineering verification, not a new release artifact or a production-accuracy claim.

## Published Release Validation (`v0.5.0`)

- The local release verification passed `429` automated tests: `428` non-E2E unit/integration/Streamlit tests and one Chromium end-to-end workflow. The measured non-E2E `src` coverage was `86.08%`.
- Report generation and revision produce a deterministic evidence-alignment review for attributable claims, citations, numbers and jurisdiction conflicts.
- The current quality contract is `governed-report-v2`, fingerprint `7c20b6fa049dc1028cc367955eb28b5434318b2d4050995cc9cf58b53a5da9d1`. The same canonical gate is recomputed for generation, revision, approval and governed export.
- Anonymous pilot aggregation and Bad Case regression tooling are ready, but the committed template still contains zero external participants.
- Privacy-minimised runtime Trace records per-stage latency, repair use and safe error codes without prompt, report, retrieval or identity content.
- The [production-aligned RAG artifact](benchmarks/rag-retrieval-v0.5.0.json) records Top-8 passage recall `1.0000`, MRR `0.9216`, Top-1 `0.8529` and safety-negative abstention `1.0000`. Its separate free-text Top-5 profile records recall `0.9706`, MRR `0.8922`, Top-1 `0.8235` and unanswerable accuracy `1.0000`.
- The [eight-case report artifact](benchmarks/report-generation-v0.5.0.json) covers all six planning scenarios, live-request refusal and no-RAG degradation. All `8/8` cases passed the governed and RAG gates with zero safety violations; repair rate was `0.625` and average latency was `46.77 seconds` on the release machine.
- Report grounding remains diagnostic and human-review-only: average support `0.9280`, citation coverage `0.2687`, citation precision `0.8571`, numeric consistency `0.9167` and zero jurisdiction conflicts. All eight reports require human evidence review.
- Both evaluation artifacts retain every per-question/per-scenario row and bind the exact source dataset SHA-256, clean source commit `e02f07687ee2e2329fc59afb5fe1c8ea4f532646`, RAG index identity and model or embedding digest. Active release runs take start/end provenance snapshots and abort before writing if any bound identity drifts.
- The committed `pilot-export-v4` Cairns Council sample passed on its first generation attempt and verifies as a 16-page PDF and 203-paragraph DOCX. It uses Ollama `bushfire-ready-qwen` through a local-loopback boundary and the same RAG manifest as both release benchmarks.
- `scripts/verify_release.py` verifies the project version, exact dataset hashes, active gates, shared Git/index provenance, current policy fingerprint and sample runtime/package bindings offline.
- Ruff, formatting, Bandit, dependency consistency and the public vulnerability audit pass.

These figures are release regression signals, not production accuracy or hardware-independent performance claims.

## Current Limitations

- It does not provide live fire conditions.
- It does not issue evacuation orders or fire bans.
- It does not confirm safe routes or safe assembly points.
- It does not replace official emergency services.
- It does not yet include authentication, role-based approvals or production deployment hardening.
- Its governed structure/safety checks and lexical evidence-alignment review do not establish factual, legal or operational correctness.
- Browser state is isolated in memory by default; optional JSON persistence is single-user only and is not a multi-user database.
- It still requires legal, licence, security, privacy and user testing before commercial or government use.
- The controlled-pilot protocol is ready, but external participant sessions have not yet run; engineering tests are not user validation.

## Best Current Positioning

Use this project as a **government-pilot MVP** or **portfolio-ready prototype**.

The right claim is:

> This is a controlled preparedness planning assistant that creates reviewable draft reports and audit records.

The wrong claim is:

> This is an emergency response or evacuation decision system.
