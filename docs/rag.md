# Local Official-Knowledge RAG

## Why it exists

The local Ollama workflow remains the default. Docker / Railway uses the optional
FastEmbed CPU backend with a pinned BGE-small model snapshot and a separate v3
index identity. See [CPU RAG validation](history/CLOUD_RAG_VALIDATION.md) for configuration,
calibration results and the held-out false-abstention limitation, and
[deployment](DEPLOYMENT.md) for read-only model assets and versioned volume seeds.
Cloud mode stops generation on RAG infrastructure errors instead of silently
using the local application's optional no-RAG fallback.

The RAG subsystem demonstrates a conventional, explainable retrieval pipeline
without weakening the project's safety boundary. It retrieves small passages
from static Australian government preparedness material before report
generation. It does not read live incidents, warnings, fire bans, evacuation
orders or confirmed safe routes.

"Official" describes the project's maintained source catalogue, not an
independent publisher-authentication or factual-verification result. Catalogue
and document hashes bind retrieved bytes to the registered records; they do
not independently certify government authority, current applicability or support
for a report statement. Missing or conflicting source identity still needs
human verification. A citation token, retrieval rank or generic evidence heading
must not promote synthetic or user-provided text into official guidance.

## Runtime flow

Since the September 12 maintenance, structured forms retain their admitted base
query results and use up to four bounded, allowlisted focus queries to fill spare
Top-K/source capacity. Supplemental candidates are rank-fused only after each
query passes the existing thresholds and a non-generic focus overlap check.
All queries share one verified index snapshot; the original live-safety refusal
still runs first. This adds embedding/query work and does not guarantee that every
selected focus has supporting text.

Production context uses `rag-context-assembly-v2`: one contiguous sentence window
per original chunk, at most 2,200 body characters and 8,000 total context
characters including framing. Adjacent qualifications are retained when detected;
this heuristic cannot reconstruct lost paragraph boundaries or prove complete
source meaning. The original single-query/v1 prefix path remains available for
historical replay. `scripts/compare_form_rag.py` measures both changes separately
without sending a report-model request. See the
[paired diagnostic and acceptance record](history/LAUNCH_READINESS_2026-09-12.md).

```text
sources.yml -> HTTPS download -> document validation -> focused multi-region extraction
            -> deterministic chunks -> Ollama embeddinggemma -> Qdrant + document snapshot

report form -> jurisdiction-aware query -> dense candidates + BM25 candidates
            -> weighted reciprocal-rank fusion -> bounded metadata rerank
            -> per-source diversity cap -> top-k passages
            -> Official Knowledge Agent -> evidence table + bounded prompt context
            -> report generation -> Evidence Trail + privacy-minimised audit metadata
```

The report form's free-text additional context is deliberately not copied into
the retrieval query. The query uses only state, locality, setting, scenario,
focus areas and timeframe. This reduces accidental disclosure and makes the
retrieval input reproducible.

## Build and evaluate

From the project root:

```powershell
ollama pull embeddinggemma
poetry run python scripts\build_rag_index.py --download
poetry run python scripts\evaluate_rag.py --warmup --output output\rag-retrieval-next.json
```

The default command evaluates two explicit profiles. `structured_planning`
matches the report retrieval configuration by enabling the trusted planning scope and using the
runtime `BUSHFIRE_RAG_TOP_K` value (8 by default); this profile controls the
process exit code and release gate. `free_text` keeps the stricter answerability
thresholds and runs at Top-5 as a diagnostic. The JSON records each profile's
query scope, Top-K, candidate limit, configured thresholds and effective
thresholds. This makes any structured-planning threshold relaxation visible.
These historical profiles query question-set text: they do not exercise the
complete form-to-query path or measure evidence remaining after prompt clipping.
The separate [form-context diagnostic](history/AUDIT_FOLLOWUP_2026-09-11.md) addresses
those boundaries without rewriting old benchmark rows or scores.
An active release artifact also includes every per-question result row for every
profile. The offline validator rejects missing or duplicate IDs and recomputes
question counts, source and passage recall, MRR, Top-1, abstention and
false-positive rate directly from those rows instead of trusting the summary.
The production profile runs all 68 answerable questions and the five
live-operation/life-safety negatives that the retrieval boundary must always
withhold. The remaining 11 arbitrary out-of-domain negatives are scoped to
`free_text`: the trusted planning profile is only reachable through a bounded,
form-built, in-domain query in the application, so treating arbitrary user text
as trusted would not represent production behavior.

For a backward-compatible free-text-only run, use:

```powershell
poetry run python scripts\evaluate_rag.py --mode free_text --top-k 5 --warmup --summary-only
```

`--mode structured_planning` without `--top-k` uses the production Top-K and is
eligible for the release gate only when full per-question rows are retained.
Supplying `--top-k` in that mode is allowed for investigation; the JSON marks
the release gate inactive whenever that value differs from the runtime
production setting. `--summary-only` also always marks the gate inactive, even
when the production Top-K is used, so a compact diagnostic cannot be mistaken
for auditable release evidence.

Use `--refresh` to re-download every declared source. The build creates local
files under `data_australia/rag/raw/` and `data_australia/rag/index/`; both are
ignored by Git. `BUSHFIRE_RAG_ENABLED=false` disables retrieval without
disabling the rest of the report pipeline.

The catalog currently covers nine official preparedness pages across all eight
Australian states and territories. Every page declares a licence URL, a reuse
classification and the date its metadata was last verified. Restricted or
ambiguous pages remain useful as local references but require permission review
before redistribution.

The committed evaluation set contains 68 answerable questions plus 16 hard
negatives. It measures source-level and passage-level Recall@K, mean reciprocal
rank, Top-1 accuracy, unanswerable accuracy, false-positive rate and latency. On
the 2026-08-22 `v0.3.0` free-text baseline, Top-5 passage recall was 0.9706, MRR
0.8922, Top-1 accuracy 0.8235, unanswerable accuracy 1.0000, average latency
133.48 ms and p95 latency 163.44 ms. These are reproducible project-benchmark
results, not evidence of production accuracy. Unit tests use a deterministic test
embedder and temporary Qdrant database, keeping CI offline and repeatable.

The current `v0.6.0` run was collected from clean commit
`44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`. The production-aligned
`structured_planning` profile ran at Top-8 over 73 questions: 68 answerable
questions plus five reachable live/life-safety negatives. It recorded passage
recall `1.0000`, MRR `0.9216`, Top-1 accuracy `0.8529`, abstention `1.0000`,
average latency `86.05 ms` and p95 latency `124.15 ms`. The same complete run
evaluated the 84-question free-text Top-5 profile and recorded passage recall
`0.9706`, MRR `0.8922`, Top-1 `0.8235`, abstention `1.0000`, average latency
`94.00 ms` and p95 latency `113.10 ms`.

The machine-readable result is committed as
[`rag-retrieval-v0.6.0.json`](benchmarks/rag-retrieval-v0.6.0.json), schema
`bushfire-rag-evaluation-v3`. It binds embedding model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`
and verified RAG manifest
`aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`.
Its call-boundary and completion provenance checks were stable. The older
[`rag-retrieval-2026-08-24.json`](benchmarks/rag-retrieval-2026-08-24.json) is
retained as historical summary evidence; it does not satisfy the current
full-row release contract.

The returned source IDs, titles, hashes and ranks are application-bound
retrieval provenance. They show which frozen passages retrieval returned, not
whether the relevant text survived clipping into the model prompt. They are not
claim-level citation accuracy, semantic entailment or
proof that a generated statement is factually correct. The separate lexical
grounding review remains diagnostic, and a human reviewer must verify any
externally used claim against the current official source.

Retrieval uses weighted reciprocal-rank fusion (0.65 dense / 0.35 BM25 by
default), then small exact-jurisdiction and title-overlap boosts. A deterministic
per-source cap prevents one long page from occupying every returned slot. The
Evidence Trail records the dense score/rank, BM25 score/rank, fused score and
rerank reasons so the result can be explained in an interview or review.

## Body claims and the submitted evidence boundary

`src/report_claim_evidence.py` adds a separate body-claim diagnostic alongside
the historical full-source and model-visible grounding results. It keeps full
sentences, list items and Markdown table cells, with source-text positions;
removing a citation does not remove the statement from its assessment scope.
Hidden HTML, comments, code and application-owned appendices are not report claims.

Citation presence, lexical support and the need for external evidence are
separate dimensions. Only validated passages from the final actual SDK request
may supply visible support. Missing or invalid capture means unknown support,
not zero risk or a reconstructed claim of what the model received. The review
UI pairs each statement with its submitted passage and review reasons, without
rewriting the recorded historical diagnostic or audit event.

The maintained generation, revision and repair instructions ask for an
unsupported local arrangement to be labelled `Unverified proposal for local
review:` in the same statement, bullet, checklist item or substantive table
cell. A disclaimer elsewhere, including another table column, does not locally
qualify that action. Factual, medical and safety assertions must not be renamed
as proposals to bypass evidence or safety requirements; missing support should
remain an explicit gap rather than an invented fact.

The current diagnostic uses lexical prefixes, not semantic understanding, to
classify uncertainty and user context. Even a factual assertion following an
"unverified proposal" prefix can receive `uncertain` / `not_required`; that is
not evidence of correctness, support or approval. The review UI explains this
per item and distinguishes official-register metadata from submitted passage
evidence. The classifier, metrics, historical validation and quality gate are
unchanged. These prompt and display changes do not establish improved model
behaviour or justify an accuracy claim from lower missing-citation counts.
The shared instructions consume the existing repair-prompt budget. Its 18,000
character cap and context-assembly limits are unchanged; very large combinations
can reach the fail-closed boundary earlier rather than receiving a larger budget.

Negation, qualifiers and numeric-context flags are conservative heuristics, not
semantic entailment. The independently authored synthetic challenge and its
subsequent **seen-case** regressions are recorded in the
[September 15 content review](history/LAUNCH_READINESS_2026-09-15.md), including failed
runs and false positives. They are separate from retrieval recall and the old
12-target visibility diagnostic. Their offline processing latency must not be
reported as real retrieval, embedding or model latency.

## Section purpose in model prompts

The maintained generator uses one application-owned `SECTION_PURPOSE_GUIDANCE`
block for initial generation, user-requested revision and structural repair.
It distinguishes preparedness priorities, communication/inclusion, and first-aid
readiness/training/exercises. A relevant citation does not by itself make a
paragraph relevant to the section where it appears.

Ordinary property-maintenance advice must not fill the first-aid section merely
because maintenance passages are available. Genuinely related training or
exercise content remains possible; this is not a keyword blacklist. If the
provided evidence does not cover a section's purpose, retain the section and
state the specific matters needing evidence or responsible local confirmation,
rather than borrowing unrelated material or inventing procedures and facts.
There is no citation quota for each section.

Structural repairs use compact context rather than replaying the original
writing instructions, so they receive the same purpose rules explicitly.
Revisions apply them within the requested edit scope; they do not authorise
silently rewriting unrelated parts of an existing report. Retrieved evidence,
its recorded assembly and historical reports are not reassigned or rewritten.

This is a prompt-contract correction, not a new semantic validator or automatic
paragraph mover. The existing v6 quality policy, audit-quality dictionaries,
repair/call limits and token budget remain unchanged. Synthetic tests can
verify that the rules reach each prompt path without changing evidence; they
cannot establish that a real model now follows the rules or that citation
coverage/semantic accuracy has improved. See [current status](project_reassessment.md)
for the recorded validation boundary. A later
[six-request synthetic comparison](experiments/evidence-generation.md#section-purpose-prompt-comparison-2026-09-29)
did not reproduce section-12 maintenance contamination in either prompt arm.
It observed clearer unknowns in one condition, but also source-identity errors
and unsupported additions. This is not a demonstrated general improvement.

The following headings preserve older links. Their full experimental records,
including failures and provenance, are archived separately and are not production
guidance. Use [current project status](project_reassessment.md) for maintained conclusions.

### Opt-in body-evidence layout experiment

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-001).

### Separately authorised DeepSeek comparison

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-002).

### Offline atomic-claim contract, not a generation pipeline

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-003).

### Independent structured selection probe

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-004).

### Offline selected-quotation review

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-005).

### Offline extractive-basis prototype

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-006).

### Bounded extractive development run

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-007).

### Offline proposal evidence boundary

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-008).

### Bounded given-basis proposal development

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-009).

### Offline selection-to-proposal handoff

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-010).

### Bounded real selection-to-proposal chain

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-011).

### Offline proposal review clues

[This experiment record now lives in Evidence-generation experiments](experiments/evidence-generation.md#evidence-generation-012).

## Integrity and prompt-injection controls

- Catalog entries require unique IDs, HTTPS URLs, bounded local paths and source metadata.
- Downloads are size-limited, retried only for transient failures and validated before atomic writes.
- HTML sources can declare one or more focused ID selectors; every selector must still exist and known WAF pages are rejected.
- Each chunk has deterministic content and identity SHA-256 values.
- Build and retrieval access to the same resolved embedded-Qdrant path is serialised inside one process; the cross-process lock has a unique owner token, reclaims an old lock only after its process is confirmed absent, and removes the lock only when the token still matches. Staged publication retains this lock, and a leftover backup is restored before any partial replacement is trusted.
- A build copies the catalog and every declared source into a private immutable snapshot, verifies the captured hashes before and after embedding, and leaves the previous index untouched if live inputs drift.
- The manifest binds catalog bytes, source bytes, canonical document snapshot, chunk corpus, embedding model and vector dimension.
- Retrieval validates the index generation at entry and exit and revalidates source bytes, the complete document snapshot, manifest, collection count, point ID and returned text hash before returning passages.
- The Python 3.13 embedded-Qdrant path derives SQLite thread safety without leaking the temporary probe connection used by the upstream client.
- Passages are delimited as untrusted quoted evidence; the model is told never to follow passage instructions.
- Prompt payloads cap total retrieved context at 8,000 characters and each passage at 2,200 characters.
- The audit stores query/source/chunk hashes and scores, but not retrieved passage text by default.
- Live-warning and life-safety queries are deterministically withheld from the static corpus, while free-text retrieval must pass lexical or combined semantic/lexical answerability thresholds.
- Release evaluation checks question bytes, Git state, RAG index and embedding-model identity before and after every warm-up and question call, and binds the manifest identity actually used by retrieval. Drift visible at those boundaries aborts an active release before an artifact is written, including A-to-B-to-A file/index/model changes across calls that a final snapshot could otherwise hide. A model-tag swap wholly inside one embedding HTTP call is not observable and is disclosed as such in new run metadata.
- Active release artifacts retain full profile rows and are re-aggregated offline; summary-only output remains diagnostic and release-inactive.

These controls make accidental corruption and common prompt-injection paths
visible. They do not make a local operator-proof or cryptographically signed
knowledge base. A person with filesystem access can replace the whole project,
sources and audit history. The benchmark is engineering regression evidence;
no real external pilot or stakeholder validation has been completed.

## Interview discussion points

- Why local Ollama embeddings match the project's privacy and offline-demo goal.
- Why jurisdiction filtering happens before dense/BM25 fusion.
- Why reciprocal-rank fusion avoids comparing incomparable raw score scales.
- Why source diversity and component ranks are part of retrieval explainability.
- Why deterministic evidence tables are rebuilt outside the LLM response.
- Why retrieval similarity is not factual correctness or source currency.
- Why the optional subsystem fails closed but does not block the core planner.
- How to extend the evaluation set with hard negatives, add learned reranking, incremental indexing and authenticated remote vector storage.
