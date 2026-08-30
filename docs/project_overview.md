# BushfireReadyGPT Project Overview

## What This Project Is

BushfireReadyGPT is an Australia-focused bushfire preparedness planning MVP. It helps a user produce a structured draft preparedness report from a selected location, audience, scenario, planning focus and review context.

The project is a governed portfolio MVP designed for controlled demonstration and pilot discussion with councils, schools and community resilience teams. External validation is still pending, and it is not an operational emergency management platform.

## What Changed From The Original Project

The original open-source project was a wildfire-oriented assistant with legacy United States data, older assistant routes and broader chat-style behaviour.

This version has been rebuilt around an Australian preparedness use case:

- Australia-specific bushfire preparedness theme.
- Form-first report generation instead of a generic chat-first workflow.
- Local Ollama runtime, so no OpenAI API key is required.
- Australia-focused deterministic component pipeline with eight named responsibility boundaries.
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
4. Seven deterministic Python components prepare local context, retrieve optional official-knowledge RAG passages and build planning evidence.
5. The stateless, tool-free local Ollama client performs the only LLM-authored step: generating the formal English report narrative.
6. The app appends governance notices, provenance-labelled evidence tables and human review sign-off, then records the canonical Governed Report Check result.
7. A follow-up edit creates a new report ID/version, rebuilds deterministic evidence, reruns the same governed gate and writes a separate audit record.
8. The reviewer checks the evidence trail, data sources, map context and governed checks, then records sign-off; every new version starts as a draft with an empty checklist.
9. Individual draft files remain available for remediation; the governed pilot package requires a fresh passing gate, exact analysis/audit binding and matching review state.
10. A historical-policy audit can be upgraded only through a policy-only `quality.reassessed` event that preserves the exact report, sign-off, status and package context. That event is not a human review, so a later `review.recorded` event is required before pilot-package export.

## Deterministic Component Architecture

The eight named agents are deterministic Python responsibility components, not eight autonomous LLM agents. Only the report-narrative step calls the LLM; retrieval, evidence selection, planning rules, quality gates and audit decisions remain application controlled.

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
- Deterministic multi-component analysis with visible intermediate evidence.
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

## Published Release Validation (`v0.6.0`)

- The release verification passes `885` automated checks: `884` non-E2E unit, integration, Streamlit and Windows-launcher tests plus one Chromium end-to-end workflow. Measured non-E2E `src` coverage is `86.95%`.
- Ruff lint/format, Bandit, Poetry/package consistency and `pip-audit` pass locally.
- The active quality contract is `governed-report-v6`, fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`. It enforces trusted scenario/focus coverage declarations, bounded governed repair, prompt-input isolation and deterministic safety checks across generation, revision, review and governed export.
- The [production-aligned RAG artifact](benchmarks/rag-retrieval-v0.6.0.json) contains `73` questions: `68` answerable cases and `5` safety negatives. Top-8 passage recall is `1.0000`, MRR `0.9216`, Top-1 `0.8529`, abstention `1.0000` and average retrieval latency `86.05 ms` on the release machine.
- RAG provenance binds the retrieval dataset, index, embedding identity and returned source records. It is application-level retrieval provenance, not proof that every model-authored claim has a correct claim-level citation.
- The [eight-case report artifact](benchmarks/report-generation-v0.6.0.json) covers all six planning scenarios, live-request refusal and no-RAG degradation. All `8/8` cases passed; average latency was `26.99 seconds`, one case required one controlled repair which succeeded, and both safety-violation and repair-exhaustion rates were `0`.
- The [six-case red-team artifact](benchmarks/report-red-team-v0.6.0.json) passed `6/6` adversarial cases, including `100%` prompt-injection resistance, with a `30.45-second` average. Every scenario-level governed gate and the suite diagnostic gate passed; its release gate is inactive by design.
- Grounding scores and evidence-alignment flags are diagnostics only. They help a reviewer find claims to inspect but do not establish semantic truth, factual correctness or approval; every generated report remains subject to human evidence review.
- All three release artifacts retain their evaluation rows and bind exact dataset hashes, clean source commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`, RAG index identity and model or embedding identity. Active runs abort instead of publishing evidence if bound provenance drifts.
- The governed showcase outputs are committed under [`examples/v0.6.0/`](../examples/v0.6.0/). Historical release artifacts remain available as immutable evidence rather than being rewritten.
- `scripts/verify_release.py` verifies the project version, datasets, active RAG/product release gates, the active red-team diagnostic gate, Git/index provenance, policy fingerprint and sample runtime/package bindings offline.
- Anonymous pilot aggregation, feedback and Bad Case tooling are ready, but no real external participant pilot has been completed. Engineering and model evaluations are not user validation.

These figures are release regression signals, not production accuracy, claim-level citation accuracy, hardware-independent performance or external user-validation claims.

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

Use this project as a **governed portfolio MVP** or **controlled-pilot
prototype with external validation pending**.

The right claim is:

> This is a controlled preparedness planning assistant that creates reviewable draft reports and audit records.

The wrong claim is:

> This is an emergency response or evacuation decision system.
