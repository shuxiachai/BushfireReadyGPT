# Project Maturity And Commercial Gap Assessment

## Current Stage

**Government-pilot MVP**

BushfireReadyGPT is strong enough for internship demonstration, portfolio presentation and controlled stakeholder pilot discussion. It is not yet ready for operational emergency use, public deployment or government procurement.

## Maturity Scores

| Area | Score | Status | Note |
| --- | --- | --- | --- |
| Product concept | 8/10 | Strong MVP | Clear Australia bushfire preparedness positioning and report workflow. |
| User workflow | 8/10 | Strong MVP | Form, demo mode, evidence trail, reviewer sign-off and export package are in place. |
| Data foundation | 6/10 | Pilot ready | ABS SA2/ASGS data is local and traceable; live warning data is not integrated. |
| Multi-agent architecture | 7/10 | Pilot ready | Agent responsibilities are separated and visible, but testing and orchestration can be strengthened. |
| Governance and audit | 7/10 | Pilot ready | v4 events bind the `governed-report-v2` policy fingerprint, exact report/review/data snapshots and recursive revision lineage. Policy-only reassessment cannot claim human review or directly authorise export; authenticated role-based approval and external immutable storage are still missing. |
| Commercial readiness | 4/10 | Not commercial yet | Needs licence review, legal boundary, deployment, privacy and user testing. |
| Government procurement readiness | 3/10 | Early | Needs security, accessibility, procurement documentation and official data agreements. |

## Completed Capabilities

- Australia-specific bushfire preparedness positioning.
- Form-first report generation instead of generic chatbot flow.
- Local Ollama model service, no OpenAI API requirement.
- Local hybrid RAG with page-level provenance, all-jurisdiction coverage, hard-negative evaluation and deterministic abstention.
- Self-checking Windows launcher, startup preflight and a dedicated 8K-context report model.
- Local multi-agent analysis pipeline with visible Evidence Trail.
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
- Full-row RAG/report release artifacts bound to exact datasets, clean source commit `e02f076`, shared index identity, exact model/embedding identities and the current quality-policy fingerprint; active release runs abort on provenance drift.
- An offline release verifier rejects stale or mismatched datasets, gates, Git/index provenance, policy and sample runtime/package identity.
- The current structured Top-8 RAG profile records recall `1.0000`, MRR `0.9216`, Top-1 `0.8529` and abstention `1.0000`; the free-text Top-5 profile records recall `0.9706`, MRR `0.8922`, Top-1 `0.8235` and abstention `1.0000`.
- The current eight-case real-model regression passed all governed and RAG gates with zero safety violations, repair rate `0.625` and average release-machine latency `46.77 seconds`. Grounding support `0.9280`, citation coverage `0.2687`, citation precision `0.8571`, numeric consistency `0.9167` and zero jurisdiction conflicts remain human-review-only; all eight reports require review.
- A current hash-verified `pilot-export-v4` Cairns Council sample that passed on its first generation attempt, with a 16-page PDF, 203-paragraph DOCX, Ollama `bushfire-ready-qwen`, local-loopback boundary and the release RAG manifest.
- Product screenshots, a short demo video and a ready-to-run controlled-pilot protocol.
- Anonymous pilot metrics, edit/citation measures and a repository-safe Bad Case regression register are ready; real sessions remain pending.
- Deterministic report evidence-alignment checks cover claim support, source attribution, numbers and jurisdiction conflicts without claiming semantic truth.
- Local privacy-minimised runtime Trace exposes per-stage latency, repair use and safe failure codes without storing report or identity content.

## Main Gaps

| Priority | Area | Gap | Next action |
| --- | --- | --- | --- |
| P0 | Safety and legal boundary | The app still needs formal legal review before commercial or government use. | Prepare a legal/disclaimer review brief and keep all outputs labelled as draft planning support. |
| P0 | Live official information | The app checks official source entry-point reachability, but does not ingest or interpret structured live warning feeds. | Keep the current panel non-decision; only add official feed integration after legal, data and operational review. |
| P1 | Data licensing | A licence register exists, but its assumptions still need commercial/legal review. | Convert licence assumptions into reviewed decisions for allowed use, attribution, caching and redistribution. |
| P1 | User testing | The report format has not been validated by real school/council/community reviewers. | Run a controlled pilot with 3-5 reviewers using the pilot feedback form. |
| P1 | Authentication and approval | Reviewer fields exist, but there are no user accounts, permissions or signed approval states. | Design roles for drafter, reviewer and admin; later add login and immutable approval records. |
| P2 | Deployment | The app runs locally and now has content-free local Trace, but is not packaged for secure hosting or central monitoring. | Add Docker, environment profiles, health checks, authenticated metrics/tracing, retention controls and deployment notes. |
| P2 | Automated testing | Local verification covers 428 non-E2E tests, one Chromium workflow, 86.08% non-E2E `src` coverage, retrieval/report release evaluation and sample-package verification. External users have not validated usefulness or comprehension. | Keep the eight-case suite as a regression baseline; add scenarios only from measured pilot findings and keep visual review in the release process. |

## Recommended Roadmap

| Phase | Goal | Work |
| --- | --- | --- |
| Now | Demo-ready portfolio MVP | Use the current screenshots, video and governed sample package for presentation; keep release checks green. |
| Next 2 weeks | Controlled pilot execution | Recruit 3-5 reviewers, run the prepared protocol, validate evidence/data-quality labels and record anonymised results. |
| Next 1-2 months | Stakeholder pilot | Test with school/council/community reviewers and refine report templates from feedback. |
| Commercial path | Procurement-ready product concept | Add authentication, deployment hardening, privacy controls, legal review and data agreements. |

## Bottom Line

The project is no longer just a modified chatbot. It is now a coherent Australian bushfire preparedness planning MVP with data evidence, multi-agent analysis, report exports and review governance.

The project now includes **Official Source Reachability**, which checks official source entry-point availability and timestamped status without making emergency decisions.

The project also includes a **Licence Register**. The next high-value commercial step is to turn that register from a pilot assumption document into a reviewed legal/commercial decision record.
