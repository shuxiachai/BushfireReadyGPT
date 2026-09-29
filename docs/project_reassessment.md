# Current project status

Updated 2026-09-29 for source-identity and proposal-review guidance. This page is the
single maintained status summary; historical model and cloud results below are
not new evaluations of the changed prompts.
Start with the [documentation index](README.md) for instructions rather than
reading historical logs as setup steps.

## Current Position

BushfireReadyGPT is a governed portfolio MVP and password-protected controlled
demonstration. It produces preparedness-planning **drafts**, not live fire
conditions, evacuation instructions, safe-place decisions or professional approval.
Upstream attribution remains in [UPSTREAM.md](../UPSTREAM.md).

| Path | Status and boundary |
| --- | --- |
| Latest formal release | **v0.6.0**, with frozen evidence from `44d0c3f`; not a new acceptance claim for later main. |
| Local use | Ollama-based, single-user demonstration through the existing Windows launcher or CLI. |
| Cloud use | Separate DeepSeek/Railway demonstration with a shared access password and container CPU RAG. |
| Maintained source | Includes later hardening, diagnostics and documented synthetic acceptance; no newer formal release is declared. |
| Experimental evidence work | Opt-in scripts and offline prototypes; not the production report generator or a semantic-accuracy gate. |

## What Is Working

- Form → selected geography/ABS context → static official-source retrieval →
  report generation → review, audit and export.
- Eight named deterministic Python components; model narration and revision are
  stateless and tool-free. They are not eight autonomous LLM agents.
- Hybrid RAG, recorded submitted evidence, data-age/geographic warnings and
  human-review diagnostics. Retrieval or lexical matches do not establish truth.
- Report/review/version bindings, hash-linked file audits, protected downloads
  and Markdown/PDF/DOCX/ZIP exports.
- Docker/Railway packaging, health checks, bounded model calls and SQLite daily
  allowance persistence. This is not a multi-user report database or distributed
  service. The shared password does not authenticate individual reviewers.

See [architecture](architecture.md), [RAG](rag.md) and
[deployment instructions](DEPLOYMENT.md) for mechanisms and constraints.

## Recorded validation

| Evidence | Recorded result | What it does not establish |
| --- | --- | --- |
| v0.6.0 release, `44d0c3f` | Frozen samples and RAG/report/red-team artifacts; [release record](releases/v0.6.0.md). | Current cloud or maintained-source accuracy. |
| Latest recorded non-E2E suite, 2026-09-29, source/proposal guidance update | 2,744 passed; 7 skipped; 6 deselected; 89.73% **src** coverage; 214.18 seconds. | Experimental-script coverage, a new six-case browser run, real-model improvement or domain correctness. |
| Section-purpose comparison, 2026-09-29, `e2e1f02` | Six single-attempt DeepSeek completions comparing `3a00f3c` and `f4ae47c`; no section-12 maintenance contamination in either arm. | A reproduced fix, generalisation, six quality-gate passes, subsequent proposal-guidance validation or new cloud acceptance. |
| Full eight-scenario model run, 2026-09-15, `0378229` | 7/8 governed checks passed; the suite did not pass overall. | The historical release's 8/8 cannot replace this result. |
| Synthetic cloud delivery, 2026-09-27, `cab29ea` | Generation, one targeted revision, draft-only review and four download formats checked; ZIP 14 files/13 hashes; all 13 actual cloud PDF pages inspected. | Word page-layout approval, semantic accuracy, restart/concurrency coverage or real-user feedback. |
| Seen selection/proposal development | Two real synthetic chains structurally valid, followed by 19 offline advisory regression cases. | Independent generalisation, semantic support or production activation. |

The [September delivery record](history/LAUNCH_READINESS_2026-09-15.md)
binds the cloud deployment, report lineage and download hashes. The
[experiment record](experiments/evidence-generation.md) keeps failed and
successful probes separate. These results have different inputs, versions and
denominators; they must not be merged into a report-accuracy percentage.

## Main Gaps

1. **Report content.** The latest cloud sample had 4 cited claims among 93
   requiring citations; its first-aid section also included home-maintenance
   material. Shared purpose and missing-evidence instructions now reach generation,
   revision and structural repair; structural checks and lexical advice still do
   not verify topic relevance. A six-request synthetic comparison found more
   explicit unknowns in one condition but did not reproduce the original failure
   in either arm; source-identity errors and unsupported additions remain.
   Later prompt and UI guidance distinguishes registered identity from authority
   verification and local proposals from supported claims; this later change
   has not received a new real-model evaluation. Prefix-based classification
   remains heuristic and can misclassify a fact labelled as a proposal.
2. **Word page layout.** Actual DOCX delivery/structure was checked, but the
   bundled renderer was unavailable. PDF inspection is not Word inspection.
3. **External validation.** [The pilot register](pilot_results.md) still records
   no completed external participants. Automated or synthetic runs are not user
   or domain-expert validation.
4. **Production governance.** Per-user roles, verified approval identities,
   multi-tenant persistence, central operations, accessibility and independent
   legal/licence/security reviews are outside the completed controlled-demo scope.

## Suggested Next Build Order

Resolve content and Word delivery gaps before publishing replacement samples
or a new release. Evaluate new content cases separately from seen development
fixtures, and retain unknowns and human review. Real stakeholder feedback is a
separate activity, not something synthetic testing can supply. Adding live
emergency decisions is not a required next feature.

## Optimisations Completed In This Review

After the September 29 documentation reorganisation, the maintained prompts
received shared section-purpose and missing-evidence guidance. Revision scope,
frozen evidence, v6 gate outputs and call budgets remain unchanged. This change
does not automatically move paragraphs, add citations or validate semantics.
The [bounded synthetic comparison](experiments/evidence-generation.md#section-purpose-prompt-comparison-2026-09-29)
records local response differences and counterexamples, not a new model-quality
or cloud acceptance pass. Previous implementation lists
and subjective maturity scores remain in the
[earlier project assessment](history/pre-reorganisation-project-reassessment.md)
and [historical commercial assessment](history/commercial_gap_assessment.md);
their former “current” statements are not the maintained status ledger.

The later source/proposal update reuses the existing shared body-claim prompt
guidance and adds fixed explanations in the review UI. It does not change
retrieval/assembly algorithms, source registration, citation classification, metric
calculations, audit schemas or safety gates, and adds no model calls. An
`uncertain` / `not_required` item still needs appropriate human review; neither
that label nor a source hash independently verifies a statement or publisher.
The 149-test targeted run covers all three prompt paths, fixed UI explanations,
historical comparison-fixture isolation and repair-budget boundaries. Shared
body-claim guidance grew from 1,207 to 1,386 characters; a previously 17,652-character
repair case now occupies 17,831 characters, while oversized cases still stop at
the unchanged 18,000-character cap. Very large inputs can reach that boundary
earlier. Independent review and repository lint/format/security checks passed;
there was no browser E2E, model or cloud acceptance rerun in this update.

## Bottom Line

Suitable for a controlled demonstration with explicit limitations, not an
operational emergency service or a fully accepted commercial release.
