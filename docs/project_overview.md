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
6. The app appends governance notices, provenance-labelled evidence tables and human review sign-off.
7. A follow-up edit creates a new report ID/version, rebuilds deterministic evidence, reruns structural checks and writes a separate audit record.
8. The reviewer checks the evidence trail, data sources, map context and structural checks, then records sign-off; every new version starts as a draft with an empty checklist.
9. The report can be exported as Markdown, PDF, DOCX or a pilot package zip.

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

## Current Validation (`v0.4.0`)

- `229` automated tests, including the Chromium end-to-end workflow, pass.
- Source coverage is `85.63%`; CI enforces an `85%` minimum on Python 3.11 and 3.13 and also validates Windows startup.
- Report generation and revision now produce a deterministic evidence-alignment review for attributable claims, citations, numbers and jurisdiction conflicts.
- The committed eight-case `v0.4.0` Ollama run passed the existing structural/RAG/safety gates; its new grounding metrics remain diagnostic and flagged all reports for human review because sentence-level citation coverage is not yet sufficient.
- Anonymous pilot aggregation and Bad Case regression tooling are ready, but the committed template still contains zero external participants.
- Privacy-minimised runtime Trace records per-stage latency, repair use and safe error codes without prompt, report, retrieval or identity content.
- The 84-question RAG baseline records Recall@5 `0.9706`, MRR `0.8922` and unanswerable accuracy `1.0000`.
- Eight real-Ollama cases cover all six planning scenarios, live-request refusal and no-RAG degradation. The committed run passed every configured release gate, averaged `27.74 seconds` on the release machine and recorded diagnostic evidence support `0.9540` versus sentence-level citation coverage `0.2311`.
- The committed sample package passes hash/schema checks and rendered PDF/DOCX visual review; the DOCX sign-off begins on a dedicated page.
- Ruff, formatting, Bandit, dependency consistency and the public vulnerability audit pass.

These figures are release regression signals, not production accuracy or hardware-independent performance claims.

## Current Limitations

- It does not provide live fire conditions.
- It does not issue evacuation orders or fire bans.
- It does not confirm safe routes or safe assembly points.
- It does not replace official emergency services.
- It does not yet include authentication, role-based approvals or production deployment hardening.
- Its structural quality checks and lexical evidence-alignment review do not establish factual, legal or operational correctness.
- Browser state is isolated in memory by default; optional JSON persistence is single-user only and is not a multi-user database.
- It still requires legal, licence, security, privacy and user testing before commercial or government use.
- The controlled-pilot protocol is ready, but external participant sessions have not yet run; engineering tests are not user validation.

## Best Current Positioning

Use this project as a **government-pilot MVP** or **portfolio-ready prototype**.

The right claim is:

> This is a controlled preparedness planning assistant that creates reviewable draft reports and audit records.

The wrong claim is:

> This is an emergency response or evacuation decision system.
