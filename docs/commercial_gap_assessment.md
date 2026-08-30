# Project Maturity And Commercial Gap Assessment

## Current Stage

**Governed portfolio MVP / controlled-pilot prototype**

BushfireReadyGPT is strong enough for internship demonstration, portfolio presentation and controlled stakeholder pilot discussion. External validation remains pending. It is not yet ready for operational emergency use, public deployment or government procurement.

## Maturity Scores

| Area | Score | Status | Note |
| --- | --- | --- | --- |
| Product concept | 8/10 | Strong MVP | Clear Australia bushfire preparedness positioning and report workflow. |
| User workflow | 8/10 | Strong MVP | Form, demo mode, evidence trail, reviewer sign-off and export package are in place. |
| Data foundation | 6/10 | Pilot ready | ABS SA2/ASGS data is local and traceable; live warning data is not integrated. |
| Multi-agent architecture | 7/10 | Pilot ready | Eight deterministic Python responsibility components are separated and visible; only report narration calls the LLM. This demonstrates governed orchestration, not autonomous tool-using agents. |
| Governance and audit | 7/10 | Pilot ready | v4 events bind `governed-report-v6` fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`, exact report/review/data snapshots and recursive revision lineage; historical policies remain readable. Policy-only reassessment cannot claim human review or directly authorise export; authenticated role-based approval and external immutable storage are still missing. |
| Commercial readiness | 4/10 | Not commercial yet | Needs licence review, legal boundary, deployment, privacy and user testing. |
| Government procurement readiness | 3/10 | Early | Needs security, accessibility, procurement documentation and official data agreements. |

## Completed Capabilities

- Australia-specific bushfire preparedness positioning.
- Form-first report generation instead of generic chatbot flow.
- Local Ollama model service, no OpenAI API requirement.
- Local hybrid RAG with page-level provenance, all-jurisdiction coverage, hard-negative evaluation and deterministic abstention.
- Self-checking Windows launcher, startup preflight and a dedicated 8K-context report model.
- Eight-role deterministic Python analysis pipeline with visible Evidence Trail; only the report narrative is LLM authored.
- A bundled small demo map plus optional all-Australia SA2/SA3/SA4 map selection.
- ABS ASGS allocation and LGA 2025 reference data.
- O1 / P2 / R3 / A4 / U0 evidence confidence and provenance labels.
- Evidence Tables appended to generated reports.
- Reviewer Approval / Human Sign-off workflow.
- Governed report revisions with new IDs, version lineage, canonical governed-quality re-checks and approval reset.
- Manifest-verified bundled core data, central data paths and transactionally published refresh bundles.
- Stateless/tool-free governed model calls with an explicit external-provider privacy boundary.
- In-memory session isolation by default and optional single-user JSON persistence without executable pickle loading.
- Audit-bound Markdown, PDF, DOCX, audit JSON and `pilot-export-v4` package with frozen registers and recursive parent lineage.
- Demo Mode, Presentation Mode and sample scenario pack.
- Source currency, age, freshness and geographic-match quality displayed in reports and Evidence Trail views.
- Full-row RAG/product/red-team release artifacts bound to exact datasets, clean source commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`, shared index identity, exact model/embedding identities and the current quality-policy fingerprint; active release runs abort on provenance drift.
- An offline release verifier rejects stale or mismatched datasets, gates, Git/index provenance, policy and sample runtime/package identity.
- The current `73`-question structured Top-8 RAG profile records recall `1.0000`, MRR `0.9216`, Top-1 `0.8529`, abstention `1.0000` and average retrieval latency `86.05 ms`.
- The current eight-case real-model regression passed `8/8` with average latency `26.99 seconds`, one successful controlled repair, zero safety violations and zero repair exhaustion. The six-case red-team regression passed `6/6`, including `100%` prompt-injection resistance, at a `30.45-second` average; every scenario-level governed gate and the suite diagnostic gate passed, while its release gate is inactive by design.
- A current hash-verified governed sample set under `examples/v0.6.0/`, using Ollama `bushfire-ready-qwen`, a local-loopback boundary and the release RAG manifest.
- Product screenshots, a short demo video and a ready-to-run controlled-pilot protocol.
- Anonymous pilot metrics, edit/citation measures and a repository-safe Bad Case regression register are ready; real sessions remain pending.
- Deterministic report evidence-alignment checks cover claim support, source attribution, numbers and jurisdiction conflicts without claiming semantic truth. Grounding remains diagnostic and requires human review.
- Local privacy-minimised runtime Trace exposes per-stage latency, repair use and safe failure codes without storing report or identity content.
- PID/token-owned audit and RAG locks protect local cross-process writes; RAG can conservatively recover sufficiently old invalid lock records while preserving live-owner locks.
- RAG records provide application-level retrieval provenance for datasets, index identity and returned sources. They do not establish claim-level citation accuracy; verified URLs are supplied only by deterministic evidence tables.
- The `v0.6.0` release passes 884 non-E2E tests plus one Chromium E2E at 86.95% measured non-E2E `src` coverage, including the user-facing BAT preflight and a fake-Ollama full Windows-launch integration test. Ruff lint/format, Bandit, Poetry/package consistency and `pip-audit` also pass locally.

## Main Gaps

| Priority | Area | Gap | Next action |
| --- | --- | --- | --- |
| P0 | Safety and legal boundary | The app still needs formal legal review before commercial or government use. | Prepare a legal/disclaimer review brief and keep all outputs labelled as draft planning support. |
| P0 | Live official information | The app checks official source entry-point reachability, but does not ingest or interpret structured live warning feeds. | Keep the current panel non-decision; only add official feed integration after legal, data and operational review. |
| P1 | Data licensing | A licence register exists, but its assumptions still need commercial/legal review. | Convert licence assumptions into reviewed decisions for allowed use, attribution, caching and redistribution. |
| P1 | User testing | The report format has not been validated by real school/council/community reviewers. | Run a controlled pilot with 3-5 reviewers using the pilot feedback form. |
| P1 | Authentication and approval | Reviewer fields exist, but there are no user accounts, permissions or signed approval states. | Design roles for drafter, reviewer and admin; later add login and immutable approval records. |
| P2 | Deployment | The app runs locally and now has content-free local Trace, but is not packaged for secure hosting or central monitoring. | Add Docker, environment profiles, health checks, authenticated metrics/tracing, retention controls and deployment notes. |
| P2 | Automated testing | The `v0.6.0` baseline covers 884 non-E2E tests at 86.95%, one Chromium workflow, 73 RAG cases, eight product cases and six adversarial cases. This is automated evidence, but no real external user has validated usefulness or comprehension. | Keep the suites as regression baselines; add scenarios from measured pilot findings and keep visual review in the release process. |

## Recommended Roadmap

| Phase | Goal | Work |
| --- | --- | --- |
| Now | Demo-ready governed portfolio MVP | Use the `v0.6.0` screenshots, video and governed sample package for presentation; keep the verified release checks green. |
| Next 2 weeks | Controlled pilot execution | Recruit 3-5 reviewers, run the prepared protocol, validate evidence/data-quality labels and record anonymised results. |
| Next 1-2 months | Stakeholder pilot | Test with school/council/community reviewers and refine report templates from feedback. |
| Commercial path | Procurement-ready product concept | Add authentication, deployment hardening, privacy controls, legal review and data agreements. |

## Bottom Line

The project is no longer just a modified chatbot. It is now a coherent Australian bushfire preparedness planning MVP with data evidence, deterministic multi-component analysis, report exports and review governance. Its eight named agents are Python responsibility boundaries rather than eight autonomous LLMs.

The project now includes **Official Source Reachability**, which checks official source entry-point availability and timestamped status without making emergency decisions.

The project also includes a **Licence Register**. The next high-value commercial step is to turn that register from a pilot assumption document into a reviewed legal/commercial decision record.
