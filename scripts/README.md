# Script navigator

Run commands from the repository root. Paths are deliberately stable: the
launcher, Docker image, CI, imports, and recorded experiment provenance refer
to them. This is a navigation index, not permission to run experiments, make
model calls, or replace recorded outputs.

## Everyday start, deployment, and checks

For a local Windows session, use the root [Windows launcher](../Start%20BushfireReadyGPT.bat)
(run `Start BushfireReadyGPT.bat --preflight` for its preflight mode), which
calls `start_app.ps1`. For a
container session, Docker's `ENTRYPOINT` is [start_container.py](start_container.py);
use the [deployment instructions](../docs/DEPLOYMENT.md) for supported
`docker run` commands and environment/corpus mounts. These are the normal paths,
not the research tools below.

| File | Executable role and boundaries |
| --- | --- |
| [start_container.py](start_container.py) | Docker entry point; prepares the runtime volume and starts Streamlit (or `--check-only`). It can write runtime state. |
| [prepare_railway_context.py](prepare_railway_context.py) | Builds a deployment context from declared inputs; writes its target context. |
| [prepare_private_corpus.py](prepare_private_corpus.py) | Creates a private-corpus bundle at its selected output path. |
| [smoke_container.py](smoke_container.py) | Container-only disposable smoke fixture; writes persistence evidence/SQLite state and uses its fixture-call allowance. |
| [run_quality_checks.ps1](run_quality_checks.ps1) | Lint, format, dependency, security, and lock checks; creates `tmp/pip-audit-cache`, invokes Poetry tools, and uses network vulnerability lookups through `pip-audit`. |

## Data, index, and routine evaluation entry points

Read the [data guide](../data_australia/README.md), [RAG setup](../docs/rag.md),
and [evaluation boundaries](../docs/evaluation_and_observability.md) first.
“Local” describes the script's own inputs only: an injected service/client or
configured embedding/model provider may still perform external or model work.

| File | Executable role and effects |
| --- | --- |
| [download_abs_asgs_allocations.py](download_abs_asgs_allocations.py) | Downloads declared ABS allocation data and writes data artifacts. |
| [download_abs_community_profiles.py](download_abs_community_profiles.py) | Downloads configured profile/boundary data and writes derived CSV/JSON artifacts. |
| [download_abs_sa2_all.py](download_abs_sa2_all.py) | Downloads the declared ABS SA2 source and writes local data artifacts. |
| [build_rag_index.py](build_rag_index.py) | Builds an index; `--download`/`--refresh` fetch sources and configured embeddings may be prepared or invoked. |
| [evaluate_rag.py](evaluate_rag.py) | Retrieval evaluation; writes its requested result and uses the configured RAG/embedding service. |
| [evaluate_form_rag.py](evaluate_form_rag.py) | Form/RAG evaluation; writes the requested artifact and runs configured analysis/RAG services. |
| [compare_form_rag.py](compare_form_rag.py) | Form/RAG comparison; writes the required output and runs configured analysis/RAG services. |
| [evaluate_report_generation.py](evaluate_report_generation.py) | Report-generation evaluation; writes artifacts and can invoke the configured model. |
| [evaluate_report_grounding.py](evaluate_report_grounding.py) | Evaluates supplied narrative/analysis JSON; optional output is local JSON. |
| [evaluate_content_quality.py](evaluate_content_quality.py) | Evaluates supplied diagnostic fixtures and writes its result artifact. |
| [evaluate_pilot_results.py](evaluate_pilot_results.py) | Summarises supplied anonymous pilot JSON; `--output` optionally writes the aggregate. |

## Release and sample entry points

Frozen [release samples](../examples/README.md) and [benchmark artifacts](../docs/benchmarks/README.md)
are historical evidence: do not regenerate them as routine housekeeping.

| File | Executable role and effects |
| --- | --- |
| [verify_release.py](verify_release.py) | Reads a committed release-evidence set and repository provenance; validation does not regenerate it. |
| [verify_sample_exports.py](verify_sample_exports.py) | Reads and verifies a selected export package (and optional standalone directory). |
| [build_showcase_sample.py](build_showcase_sample.py) | Creates a new chosen output directory; requires its local Ollama runtime and refuses an existing output directory. |

## Experiment entry points: recorded boundaries

Read the [experiment record](../docs/experiments/evidence-generation.md) and
[current project status](../docs/project_reassessment.md) first. Model-gated
tools require explicit arguments and authorization; journals, counters, and
output paths are part of their evidence. A flag does not permit a new campaign.

| Area | Entrypoints and status |
| --- | --- |
| Body-evidence layout | [evaluate_body_evidence_ab.py](evaluate_body_evidence_ab.py) prepares/evaluates the A/B artifact; [evaluate_body_evidence_deepseek.py](evaluate_body_evidence_deepseek.py) writes a journal/output and permits external DeepSeek only with both explicit model flags. |
| Atomic selection/review | [evaluate_atomic_claim_deepseek.py](evaluate_atomic_claim_deepseek.py) is the model-gated, journaled evaluator; its output/call limits remain part of its contract. |
| Fixed section-purpose comparison — closed | [section_scope_comparison.py](section_scope_comparison.py) is the frozen synthetic `3a00f3c` → `f4ae47c` six-case campaign. Current source drift intentionally fails provenance validation; do not rerun or reopen its journal. |
| Frozen provenance/scope comparison — closed | [scoped_basis_comparison.py](scoped_basis_comparison.py) prepares/validates the historical offline `933d26b` → `f69e62f` six-case bundle; [run_scoped_basis_comparison.py](run_scoped_basis_comparison.py) was its separate single-attempt execution. Neither flags nor renamed outputs reopen it. |
| Citation/task/criterion comparison — closed | [citation_criteria_comparison.py](citation_criteria_comparison.py) prepares/validates the synthetic `3199c7d` → `b74cdd8` cases; [run_citation_criteria_comparison.py](run_citation_criteria_comparison.py) recorded six authorized single attempts with its fixed claim/SQLite counter. No retry, repair, model judge, replacement, or reopening. |

## Import-only modules

These 14 Python files have no `__main__` guard. They are library modules for
an importing caller, not ordinary command-line entry points; effects depend on
the caller's arguments, supplied clients, and selected paths.

| Module | Imported purpose |
| --- | --- |
| [atomic_claim_adapter.py](atomic_claim_adapter.py) | Builds/validates atomic-selection requests and exposes SDK invocation helpers. |
| [atomic_claim_advisory.py](atomic_claim_advisory.py) | Produces local selection-review advisory data from supplied material. |
| [atomic_claim_contract.py](atomic_claim_contract.py) | Parses, validates, and renders atomic evidence-pack records. |
| [body_evidence_experiment.py](body_evidence_experiment.py) | Prompt variants, claim-pair parsing, and per-arm evaluation helpers. |
| [evaluation_artifacts.py](evaluation_artifacts.py) | Artifact hashing, validation and provenance; optional Ollama identity lookup makes an HTTP request. |
| [extractive_basis_prototype.py](extractive_basis_prototype.py) | Extractive-basis prototype construction/validation helpers. |
| [extractive_development.py](extractive_development.py) | Pure extractive-suite preparation, request construction, validation and result summarisation. |
| [proposal_evidence_advisory.py](proposal_evidence_advisory.py) | Proposal evidence-review advisory helpers. |
| [proposal_evidence_contract.py](proposal_evidence_contract.py) | Proposal evidence structures and validation helpers. |
| [proposal_development.py](proposal_development.py) | Pure proposal-suite preparation, request construction, validation and result summarisation. |
| [release_paths.py](release_paths.py) | Caller-supplied release-path resolution and validation. |
| [report_content_advisory.py](report_content_advisory.py) | Caller-supplied literal-target, citation-association, and occurrence-qualification review; no standalone file/network/model entry point. |
| [selection_proposal_bridge.py](selection_proposal_bridge.py) | Selection-to-proposal handoff construction and validation helpers. |
| [selection_proposal_development.py](selection_proposal_development.py) | Journaled selection/proposal development-suite helpers, including supplied model invocation paths. |
