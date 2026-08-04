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
- VSCode startup task and local PowerShell startup script.

## Current User Workflow

1. The user opens the Streamlit app.
2. The user loads a pilot example or fills in the report form.
3. The user selects the location, audience, scenario, timeframe and focus areas.
4. The multi-agent pipeline prepares local context and planning evidence.
5. The local Ollama model generates a formal English draft report.
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
- Human review and approval boundary.
- Versioned, governed report revisions with approval reset and per-version audit files.
- Evidence tables and audit records.
- Evidence provenance labels that separate official references, processed data, deterministic inference, AI prose and unverified inputs.
- Export to Markdown, PDF, DOCX and pilot package zip.
- Commercial gap and project maturity assessment.

## Current Limitations

- It does not provide live fire conditions.
- It does not issue evacuation orders or fire bans.
- It does not confirm safe routes or safe assembly points.
- It does not replace official emergency services.
- It does not yet include authentication, role-based approvals or production deployment hardening.
- Its quality checks verify structure and safety wording only; they do not establish factual, legal or operational correctness.
- Browser state is isolated in memory by default; optional JSON persistence is single-user only and is not a multi-user database.
- It still requires legal, licence, security, privacy and user testing before commercial or government use.

## Best Current Positioning

Use this project as a **government-pilot MVP** or **portfolio-ready prototype**.

The right claim is:

> This is a controlled preparedness planning assistant that creates reviewable draft reports and audit records.

The wrong claim is:

> This is an emergency response or evacuation decision system.
