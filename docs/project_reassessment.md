# BushfireReadyGPT Project Reassessment

## Current Position

BushfireReadyGPT is a working Australia-focused governed portfolio MVP and
controlled-pilot prototype. Published release `v0.6.0` is the current evidence
baseline; earlier releases remain immutable historical evidence. The project
has a form-first workflow, deterministic multi-component analysis,
conventional local RAG, ABS/ASGS evidence context, report evidence-alignment
diagnostics, explicit data-quality warnings, official source registers, human
review controls and exportable report packages.

The strongest current use case is a controlled pilot demonstration for councils, schools, community organisations or internship assessment. It should still be presented as draft planning support, not as an operational emergency platform.

## What Is Working

| Area | Current state |
| --- | --- |
| Product workflow | Clear form-to-report flow with review/export tabs. |
| Multi-agent layer | Seven pre-generation roles and one post-generation quality role are separated as deterministic Python components. They are not autonomous LLM agents; only the report narrative is model generated. |
| Australian data context | Local ABS/ASGS processed data and official source registers are available. |
| Governance boundary | One canonical gate is recomputed across generation, revision, organisational approval and governed `pilot-export-v4` export. Current records bind `governed-report-v6` fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`, trusted scenario/focus coverage declarations, full-analysis hash, exact report/review/data snapshots, deterministic sign-off and recursively verifiable version lineage. Historical policies remain readable. A policy-only reassessment preserves report/sign-off/status/package context and cannot substitute for the later human review required for export. |
| Exports | Markdown, PDF, DOCX and `pilot-export-v4` zip package are implemented. |
| Local model runtime | Ollama is the default provider; an 8K dedicated model is called through a stateless, tool-free governed client. |
| Official knowledge RAG | Nine page-level sources cover all states/territories with hybrid retrieval, abstention and answerable/unanswerable evaluation. |
| Report evidence evaluation | Attributable claims receive deterministic support, citation, numeric and jurisdiction checks. These are diagnostics for human source review, not semantic-truth or claim-level citation guarantees. |
| Runtime diagnosis | Privacy-minimised local Trace captures per-agent/model stages, latency, repair use and safe failure codes without report or identity content. |
| Local setup | One self-checking Windows launcher reuses healthy dependencies, models and RAG assets and creates only missing or outdated components. |
| Testing | The `v0.6.0` release passes 884 non-E2E tests plus one Chromium E2E with measured non-E2E `src` coverage of 86.95%; Ruff lint/format, Bandit, Poetry/package consistency and `pip-audit` also pass locally. |
| Portfolio evidence | The governed sample set is committed under `examples/v0.6.0/` and binds the release runtime and RAG evidence. Screenshots, a short demo video and a controlled-pilot protocol are also committed; no real external pilot has yet been completed. |

The `v0.6.0` production-aligned retrieval profile contains `73` questions and records Top-8 passage recall `1.0000`, MRR `0.9216`, Top-1 accuracy `0.8529`, safety-negative abstention `1.0000` and average retrieval latency `86.05 ms`. Retrieval provenance binds the application inputs, index, embedding identity and returned sources; it does not prove claim-level citation accuracy. The eight-case real-Ollama report benchmark covers all six planning scenarios, live-request refusal and no-RAG degradation: all `8/8` cases passed with average latency `26.99 seconds`, one successful controlled repair, zero safety violations and zero repair exhaustion. The six-case red-team benchmark passed `6/6`, including `100%` prompt-injection resistance, at an average of `30.45 seconds`; every scenario-level governed gate and the suite diagnostic gate passed, while its release gate is inactive by design. Grounding remains diagnostic and every generated report still requires human evidence review. These are regression baselines rather than factual-accuracy, production or external user-validation claims.

The committed RAG, product and red-team artifacts include every evaluation row and each binds its exact dataset hash, clean source commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7` and the shared RAG index. The RAG artifact binds the embedding identity; the product and red-team artifacts bind the generation-model identity and `governed-report-v6` fingerprint. Active release runs abort on provenance drift, and the offline release verifier rejects inactive or failed required RAG/product release gates, an inactive or failed red-team diagnostic gate, stale datasets or policy, mismatched commit/index provenance, or a sample produced through a different provider, model, endpoint boundary or RAG manifest. The red-team release gate remains inactive by design. PID/token-owned audit and RAG locks protect cross-process state, and verified URLs remain application-bound evidence rather than model-authored trust claims.

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
- Added full-row RAG/report release artifacts with exact dataset, Git and index provenance plus start/end drift detection; the RAG artifact binds the embedding identity, while both report artifacts bind the generation-model identity and quality policy.
- Added policy-only quality reassessment for unchanged historical reports; it never claims human review and cannot be the export head without a later review event.
- Added an offline release verifier that ties `v0.6.0` metadata, the two active passing release gates, the active passing red-team diagnostic gate and the governed sample package to one reproducible evidence set.
- Unified audit and RAG cross-process ownership around PID/token lock records; RAG can conservatively reclaim sufficiently old invalid records while preserving live-owner locks.
- Standardised model-authored RAG citations as `[O1-RAG][source_id=...] <title>` and removed model-authored URLs from the trust contract; deterministic evidence tables bind the verified links.
- Added a fake-Ollama full Windows-launch integration test, a single PowerShell quality-check wrapper with UTF-8-safe dependency auditing and a root `/tmp/` ignore rule.
- Upgraded the contract to `governed-report-v6`, deriving required scenario/focus declarations only from trusted canonical IDs, isolating U0 text from control instructions and bounding governed repair without a deterministic fallback report.
- Added a six-case adversarial suite for U0 field overrides, governance removal, forged tool/HTML output and delimiter-based prompt/live-route leakage; all cases pass while grounding results remain explicitly diagnostic and human-review-only.

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

The project is suitable as a serious governed portfolio MVP and
controlled-pilot prototype. External validation remains pending. The next major
difference between a good internship project and a commercial product is not
another visual redesign. The next step is governance: validated confidence
rules, traceable approval, legal/licence clarity and deployment hardening.
