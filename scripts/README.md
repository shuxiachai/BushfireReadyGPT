# Script navigator

Run commands from the repository root. Script paths remain unchanged because
the launcher, Docker, CI, imports and experimental provenance refer to them.
This index distinguishes runnable tools from importable helpers; it does not
activate experiments or authorise additional model calls.

## Start and deploy

- [start_container.py](start_container.py): container entry point; normally invoked by Docker.
- [prepare_railway_context.py](prepare_railway_context.py): prepare the deployment build context.
- [prepare_private_corpus.py](prepare_private_corpus.py): prepare a declared private corpus bundle.
- [smoke_container.py](smoke_container.py): disposable container smoke checks.
- [run_quality_checks.ps1](run_quality_checks.ps1): local quality-check wrapper.

Use the root [Windows launcher](../Start%20BushfireReadyGPT.bat) for local Ollama
and follow [deployment instructions](../docs/DEPLOYMENT.md) for the cloud path.

## Data and index preparation

- [download_abs_asgs_allocations.py](download_abs_asgs_allocations.py)
- [download_abs_community_profiles.py](download_abs_community_profiles.py)
- [download_abs_sa2_all.py](download_abs_sa2_all.py)
- [build_rag_index.py](build_rag_index.py)

These can download data, write local assets or invoke embeddings. Read the
[data guide](../data_australia/README.md) and [RAG setup](../docs/rag.md) first.

## Evaluation and diagnostics

- [evaluate_rag.py](evaluate_rag.py): retrieval evaluation.
- [evaluate_report_generation.py](evaluate_report_generation.py): report-generation regression.
- [evaluate_report_grounding.py](evaluate_report_grounding.py): report evidence diagnostics.
- [evaluate_content_quality.py](evaluate_content_quality.py): content-quality diagnostic fixtures.
- [evaluate_form_rag.py](evaluate_form_rag.py) and [compare_form_rag.py](compare_form_rag.py): form/context diagnostics and comparisons.
- [evaluate_pilot_results.py](evaluate_pilot_results.py): anonymous pilot aggregates.

Some evaluators call real models or embeddings; they are not interchangeable
with offline unit tests. Use their existing help and authorisation controls.
Definitions and boundaries are in [evaluation and observability](../docs/evaluation_and_observability.md).

## Release and sample verification

- [verify_release.py](verify_release.py): offline verification of a committed release evidence set.
- [verify_sample_exports.py](verify_sample_exports.py): export-package integrity and lineage checks.
- [build_showcase_sample.py](build_showcase_sample.py): generate a new sample; may call the model and refuses to overwrite existing outputs.
- [release_paths.py](release_paths.py) and [evaluation_artifacts.py](evaluation_artifacts.py): shared helpers, not ordinary starting points.

Frozen [release samples](../examples/README.md) and
[benchmark artifacts](../docs/benchmarks/README.md) are historical evidence.
Do not regenerate them during routine housekeeping.

## Optional experimental work

Read the [experiment record](../docs/experiments/evidence-generation.md) before
using these tools. Pure helpers do not prove the semantic quality of a model
response. Remote entry points have explicit authorisation and bounded journals;
renaming outputs or deleting journals must not reopen a completed campaign.

| Experiment | Entry points and helpers |
| --- | --- |
| Body-evidence layout | [evaluate_body_evidence_ab.py](evaluate_body_evidence_ab.py), [evaluate_body_evidence_deepseek.py](evaluate_body_evidence_deepseek.py), [body_evidence_experiment.py](body_evidence_experiment.py) |
| Atomic selection and review | [evaluate_atomic_claim_deepseek.py](evaluate_atomic_claim_deepseek.py), [atomic_claim_adapter.py](atomic_claim_adapter.py), [atomic_claim_contract.py](atomic_claim_contract.py), [atomic_claim_advisory.py](atomic_claim_advisory.py) |
| Whole-unit selection | [extractive_basis_prototype.py](extractive_basis_prototype.py), [extractive_development.py](extractive_development.py) |
| Proposal dependencies and review | [proposal_evidence_contract.py](proposal_evidence_contract.py), [proposal_development.py](proposal_development.py), [proposal_evidence_advisory.py](proposal_evidence_advisory.py) |
| Selection-to-proposal handoff | [selection_proposal_bridge.py](selection_proposal_bridge.py), [selection_proposal_development.py](selection_proposal_development.py) |
| Fixed section-purpose comparison | [section_scope_comparison.py](section_scope_comparison.py): frozen `3a00f3c` → `f4ae47c` synthetic campaign, now closed. Later source changes intentionally fail its provenance checks; the existing journal must not be reopened. |
| Frozen provenance/scope comparison | [scoped_basis_comparison.py](scoped_basis_comparison.py): historical offline-only preparation and validation, `933d26b` → `f69e62f`. Later source maintenance intentionally fails its current-checkout provenance guard; historical test fixtures do not reopen the campaign. |
| Authorised provenance/scope execution | [run_scoped_basis_comparison.py](run_scoped_basis_comparison.py): separate six-request, single-attempt execution of the unchanged frozen bundle; campaign now closed. The fixed claim prevents rerunning it. Flags do not authorise a new campaign. |

[Current project status](../docs/project_reassessment.md) separates these
development results from production behaviour and release acceptance.
