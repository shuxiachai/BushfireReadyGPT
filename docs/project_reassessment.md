# BushfireReadyGPT Project Reassessment

## Current Position

BushfireReadyGPT `v0.5.0` is a working Australia-focused bushfire preparedness planning MVP. It is no longer just a renamed chatbot. The project has a form-first workflow, deterministic multi-agent analysis, conventional local RAG, ABS/ASGS evidence context, report evidence-alignment diagnostics, explicit data-quality warnings, official source registers, human review controls and exportable report packages.

The strongest current use case is a controlled pilot demonstration for councils, schools, community organisations or internship assessment. It should still be presented as draft planning support, not as an operational emergency platform.

## What Is Working

| Area | Current state |
| --- | --- |
| Product workflow | Clear form-to-report flow with review/export tabs. |
| Multi-agent layer | Seven pre-generation agents, including Official Knowledge RAG, and one post-generation quality agent are separated. |
| Australian data context | Local ABS/ASGS processed data and official source registers are available. |
| Governance boundary | One canonical gate is recomputed across generation, revision, organisational approval and governed `pilot-export-v4` export; v4 events bind `governed-report-v2` fingerprint `7c20b6fa049dc1028cc367955eb28b5434318b2d4050995cc9cf58b53a5da9d1`, the full-analysis hash, exact report/review/data snapshots, deterministic sign-off and recursively verifiable version lineage. A policy-only reassessment preserves report/sign-off/status/package context and cannot substitute for the later human review required for export. |
| Exports | Markdown, PDF, DOCX and `pilot-export-v4` zip package are implemented. |
| Local model runtime | Ollama is the default provider; an 8K dedicated model is called through a stateless, tool-free governed client. |
| Official knowledge RAG | Nine page-level sources cover all states/territories with hybrid retrieval, abstention and answerable/unanswerable evaluation. |
| Report evidence evaluation | Attributable claims receive deterministic support, citation, numeric and jurisdiction checks; flags remain subject to human source review. |
| Runtime diagnosis | Privacy-minimised local Trace captures per-agent/model stages, latency, repair use and safe failure codes without report or identity content. |
| Local setup | One self-checking Windows launcher reuses healthy dependencies, models and RAG assets and creates only missing or outdated components. |
| Testing | The local release verification passes 429 automated tests (428 non-E2E plus one Chromium E2E), with measured non-E2E `src` coverage of 86.08%. |
| Portfolio evidence | The current Cairns Council sample uses Ollama `bushfire-ready-qwen` through a local-loopback boundary and the release RAG manifest; its `pilot-export-v4` package contains a 16-page PDF and 203-paragraph DOCX generated successfully on the first attempt. Screenshots, a short demo video and a controlled-pilot protocol are also committed; external pilot results remain pending. |

The current production-aligned retrieval profile records Top-8 passage recall `1.0000`, MRR `0.9216`, Top-1 accuracy `0.8529` and safety-negative abstention `1.0000`. The separate free-text Top-5 diagnostic records recall `0.9706`, MRR `0.8922`, Top-1 accuracy `0.8235` and unanswerable accuracy `1.0000`. The `v0.5.0` eight-case real-Ollama report benchmark covers all six planning scenarios, live-request refusal and no-RAG degradation: all `8/8` cases passed the governed and RAG gates, safety violations were zero, repair rate was `0.625` and average latency was `46.77 seconds` on the release machine. Diagnostic grounding measured average support `0.9280`, citation coverage `0.2687`, citation precision `0.8571`, numeric consistency `0.9167` and zero jurisdiction conflicts; all eight reports still require human evidence review. These are regression baselines rather than factual-accuracy, production or external user-validation claims.

The committed RAG and report artifacts include every evaluation row and bind exact dataset hashes, clean source commit `e02f07687ee2e2329fc59afb5fe1c8ea4f532646`, the shared RAG index and exact model/embedding identities. Active release runs abort on end-of-run provenance drift, and the offline release verifier rejects inactive gates, stale datasets or policy, mismatched commit/index provenance, or a sample produced through a different provider, model, endpoint boundary or RAG manifest.

## Main Gaps

| Priority | Gap | Why it matters | Recommended action |
| --- | --- | --- | --- |
| P0 | Legal and licence review is incomplete | Commercial or government use requires clear reuse rights, liability boundaries and procurement-safe wording. | Keep outputs as drafts; expand the licence register; prepare a legal review brief. |
| P0 | No authenticated approval workflow | Current reviewer fields are useful for pilots but not enough for formal approval records. | Add user roles, login, signed identities and externally anchored/WORM audit retention. |
| P0 | No live emergency interpretation | The app must not imply real-time warnings, evacuation status or safety decisions. | Keep the official status panel as source reachability only; add stricter copy around non-decision use. |
| P1 | Data matching is still pilot-level | Source age and geographic-match quality are now visible, but some community vulnerability matches remain approximations. | Validate the new P2/R3 confidence and data-quality boundaries with data and GIS owners, then replace approximations where required. |
| P1 | Accessibility and procurement readiness not checked | Government buyers often require accessibility, security and maintainability evidence. | Add WCAG review, deployment docs, privacy statement and security checklist. |
| P1 | UI is visually stronger but still Streamlit-limited | Streamlit is fine for MVP, but commercial UX may need a dedicated frontend. | Keep Streamlit for demo; plan a future React/FastAPI version if commercial traction appears. |
| P2 | No persistent database | Current local files are fine for prototypes but weak for multi-user pilots. | Add SQLite/PostgreSQL for reports, audits, users and data refresh logs. |
| P2 | No central production observability | Local content-free Trace supports single-user diagnosis but has no remote exporter, cross-instance correlation, alerting or retention service. | Define privacy/retention controls before adding authenticated central metrics and tracing for a deployed service. |

## Optimisations Completed In This Review

- Fixed the Report Quality Agent checklist detection by removing a corrupted legacy checkbox string.
- Added a Human Review Status quality check.
- Added report validation so reviewed or approved reports require organisation, reviewer name and reviewer role.
- Moved reviewer identity out of report creation and into the accountable Review & Export step.
- Replaced the legacy Assistant Router, provider thread and compatibility helpers with a small stateless `GovernedModelClient`.
- Added tests for approval validation and quality checklist detection.
- Added O1 / P2 / R3 / A4 / U0 provenance labels to analysis, reports, audits, UI review and quality checks.
- Routed follow-up edits through a governed revision workflow with report IDs, version lineage, new audit records and deterministic evidence regeneration.
- Reset prior approval/checklist state on each new version and require identity fields plus a complete checklist before organisational approval.
- Replaced shared pickle state with isolated in-memory sessions by default and optional single-user JSON persistence.
- Separated map preview from active report geography and rejected cross-state form/map conflicts.
- Added privacy-minimised, append-only hash-linked audit events with report/review binding, per-report locking and export-chain verification.
- Upgraded governed records to v4 with positive versions, deterministic sign-off, frozen register snapshots, single-child revision claims, recursive ancestry and interrupted-write recovery.
- Centralised active data paths, verified bundled files against a manifest before analysis and added before/after provenance checks.
- Made all three data rebuilders validate and transactionally publish complete bundles with recovery metadata.
- Made governed model calls stateless and tool-free, with explicit acknowledgement before any external endpoint receives report inputs.
- Added a locked Poetry environment, coverage threshold, static analysis, dependency audit and pinned CI actions.
- Added page-level licensed local RAG, all-jurisdiction coverage, hard negatives and a real-model report benchmark.
- Tuned the dedicated local model to an 8K context, 2,300 output tokens and a 900-1,200-word narrative budget; reduced RAG and revision prompt payloads.
- Added HTTPS-only external endpoints, interrupted-stream handling and structural repair without provider-side conversation memory.
- Added a single self-checking Windows launcher, startup/preflight CI, concurrent source reachability checks, formatting enforcement and a complexity ceiling.
- Added a Python 3.13 Qdrant/SQLite compatibility shim, raised the coverage gate to 85% and verified dependencies against the public vulnerability database.
- Added source-period, latest-year, age, freshness and geographic-match warnings to governed reports and Evidence Trail views.
- Expanded the real-model benchmark from three cases to all six scenarios plus safety-boundary and no-RAG behavior cases.
- Built and hash-verified a current Cairns Council Markdown/PDF/DOCX sample package, then visually reviewed every PDF and DOCX page.
- Added current product screenshots, a short demo video and a repeatable 3-5 person controlled-pilot protocol with an honest pending-results register.
- Added a strict anonymous pilot-measurement schema, calculated aggregates and Bad Case-to-regression linkage while keeping the committed template at zero participants.
- Added deterministic report evidence-alignment review for claim support, source attribution, numeric consistency and jurisdiction conflicts.
- Added privacy-minimised per-stage runtime Trace and local Readiness diagnostics, separate from the governance audit chain.
- Added full-row RAG/report release artifacts with exact dataset, Git, index, model/embedding and quality-policy provenance plus start/end drift detection.
- Added policy-only quality reassessment for unchanged historical reports; it never claims human review and cannot be the export head without a later review event.
- Added an offline release verifier that ties `v0.5.0` metadata, both passing release gates and the governed sample package to one reproducible evidence set.

## Suggested Next Build Order

1. **Controlled stakeholder validation**
   Run the prepared protocol with 3-5 school, council or community reviewers and record anonymised measures without turning engineering tests into user-validation claims.

2. **Evidence confidence validation**
   Review O1 / P2 / R3 / A4 / U0 labels and the implemented freshness/match warnings with data, GIS and emergency-management stakeholders.

3. **Legal and licence review brief**
   Turn the current source/licence register and safety language into a review pack for a qualified legal or risk advisor.

4. **Approval workflow v2**
   Add named user roles and immutable approval records so a report can move from draft to reviewed to approved.

5. **Deployment plan**
   Add Docker, environment profiles, health checks and a privacy/security note for external demonstrations.

## Bottom Line

The project is suitable as a serious MVP demonstration. The next major difference between a good internship project and a commercial product is not another visual redesign. The next step is governance: validated confidence rules, traceable approval, legal/licence clarity and deployment hardening.
