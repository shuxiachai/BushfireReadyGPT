# Documentation Index

This folder contains project explanation, demo, governance and commercial-readiness materials for BushfireReadyGPT.

## Fast Reading Path

If you only have a few minutes, read these in order:

1. `project_overview.md` - what the project is and what it is not.
2. `demo_walkthrough.md` - how to demonstrate the app.
3. `../examples/v0.5.0/README.md` - published Markdown, PDF, DOCX and governed package.
4. `commercial_gap_assessment.md` - what remains before commercial or government use.

## Start Here

| File | Purpose |
| --- | --- |
| `showcase_package.md` | Main entry point for presentation and portfolio materials. Read this first before preparing a demo. |
| `project_overview.md` | Plain project explanation for someone seeing the project for the first time. |
| `demo_walkthrough.md` | Step-by-step live demonstration flow. Use this when presenting the app. |
| `showcase_checklist.md` | Pre-presentation checklist for setup, demo flow, exports and safety boundary. |

## Product And Pilot Materials

| File | Purpose |
| --- | --- |
| `../examples/v0.5.0/README.md` | Published v0.5.0 local-Ollama sample in Markdown, PDF and DOCX plus its `pilot-export-v4` package. |
| `../examples/v0.3.0/README.md` | Historical governed sample retained for comparison. |
| `assets/bushfire-ready-gpt-demo.webm` | 89-second local product demonstration. |
| `pilot_pitch.md` | One-page pilot pitch for councils, schools or community stakeholders. |
| `pilot_feedback_form.md` | Structured feedback form for a controlled stakeholder pilot. |
| `pilot_protocol.md` | Privacy-minimised 3-5 person controlled-pilot procedure and completion gate. |
| `pilot_results.md` | Anonymised result register; it remains explicitly pending until real sessions run. |
| `pilot_evaluation_template.json` | Strict repository-safe schema template for anonymous measures and Bad Case references. |
| `demo_scenarios.md` | Written reference for the built-in demo scenarios. |

## Technical And Governance Materials

| File | Purpose |
| --- | --- |
| `architecture.md` | Technical architecture, agent responsibilities and data flow. |
| `rag.md` | Local official-knowledge RAG build, evaluation, integrity and trust boundary. |
| `evaluation_and_observability.md` | Report evidence-alignment evaluation, pilot metrics and privacy-minimised runtime Trace. |
| `project_reassessment.md` | Current project status, gaps and recommended next build order. |
| `commercial_gap_assessment.md` | Commercial and government-readiness gap assessment. |
| `commercial_readiness_checklist.md` | Checklist of what is done and what remains before commercial positioning. |
| `licence_register.md` | Explanation of licence assumptions tracked in `data_australia/licence_register.yml`. |
| `releases/v0.1.0.md` | Scope, highlights, validation and limitations for the first public MVP release. |
| `releases/v0.2.0.md` | RAG, local setup, safety hardening and validation notes for the portfolio release. |
| `releases/v0.2.1.md` | Launcher, performance, model-runtime, UI and test hardening maintenance release. |
| `releases/v0.3.0.md` | Data-quality, scenario benchmark, sample package, visual QA and pilot-readiness release. |
| `releases/v0.4.0.md` | Evidence-alignment, anonymous pilot measurement and privacy-minimised runtime Trace release. |
| `releases/v0.5.0.md` | Reproducible release evidence, governed quality-policy binding and offline verification release. |
| `benchmarks/rag-retrieval-v0.5.0.json` | Published Top-8 release gate and Top-5 diagnostic with dataset, model, index and Git provenance. |
| `benchmarks/report-generation-v0.5.0.json` | Published eight-scenario governed real-Ollama gate with diagnostic grounding metrics. |
| `benchmarks/report-generation-v0.3.0.json` | Historical eight-case real-Ollama regression result. |
| `benchmarks/report-generation-v0.4.0.json` | Historical grounding-diagnostic regression result. |

## Current Release Evidence

v0.5.0 is bound to source commit `e02f076`. The release verification set records
429 passing tests (428 non-E2E plus one Chromium E2E) and 86.08% coverage. The
RAG release gate evaluates 73 structured Top-8 questions; the free-text Top-5
diagnostic evaluates all 84 questions. The report gate evaluates eight scenarios.
See the two v0.5.0 benchmark JSON files and `../examples/v0.5.0/README.md` for the
exact measured rates, provenance and limitations.

## Maintained Working Tree

The v0.6.0 release-candidate working tree was checked locally on 2026-08-29 with
`584` passing non-E2E tests and `86.75%` measured `src` coverage. Ruff lint/format,
Bandit, Poetry/package consistency and `pip-audit` also pass locally. The
hardening includes PID/token-owned audit and RAG locks with conservative stale
record recovery, canonical `[O1-RAG][source_id=...] <title>` model citations
with deterministic URL binding, a fake-Ollama Windows full-launch test, one
PowerShell quality-check wrapper and root `/tmp/` exclusion. These local values
are not a new release or a remote-CI claim; the immutable `v0.5.0` evidence above
remains unchanged.

## Removed Redundant Docs

The older `demo_guide.md` and `demo_script.md` files were removed because their content is now covered more clearly by:

- `demo_walkthrough.md`
- `showcase_package.md`
- `showcase_checklist.md`

## Recommended Use

For an internship or coursework presentation:

1. Read `project_overview.md`.
2. Use `demo_walkthrough.md` during the live demo.
3. Check `showcase_checklist.md` before presenting.
4. Use `project_reassessment.md` to explain what is still missing before commercial use.

For a stakeholder or pilot discussion:

1. Start with `pilot_pitch.md`.
2. Demonstrate using `demo_walkthrough.md`.
3. Run sessions with `pilot_protocol.md` and collect feedback with `pilot_feedback_form.md`.
4. Record anonymised evidence in `pilot_results.md`.
5. Discuss maturity using `commercial_gap_assessment.md`.

For GitHub reviewers:

1. Start from the root `README.md`.
2. Open the current sample output in `examples/v0.5.0/`.
3. Read `architecture.md` only if they want implementation details.
4. Read `rag.md` for the retrieval design and evaluation story.
5. Read `commercial_gap_assessment.md` to understand current limits.
