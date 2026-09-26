# Local Official-Knowledge RAG

## Why it exists

The local Ollama workflow remains the default. Docker / Railway uses the optional
FastEmbed CPU backend with a pinned BGE-small model snapshot and a separate v3
index identity. See [CPU RAG validation](CLOUD_RAG_VALIDATION.md) for configuration,
calibration results and the held-out false-abstention limitation, and
[deployment](DEPLOYMENT.md) for read-only model assets and versioned volume seeds.
Cloud mode stops generation on RAG infrastructure errors instead of silently
using the local application's optional no-RAG fallback.

The RAG subsystem demonstrates a conventional, explainable retrieval pipeline
without weakening the project's safety boundary. It retrieves small passages
from static Australian government preparedness material before report
generation. It does not read live incidents, warnings, fire bans, evacuation
orders or confirmed safe routes.

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
[paired diagnostic and acceptance record](LAUNCH_READINESS_2026-09-12.md).

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
The separate [form-context diagnostic](AUDIT_FOLLOWUP_2026-09-11.md) addresses
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

Negation, qualifiers and numeric-context flags are conservative heuristics, not
semantic entailment. The independently authored synthetic challenge and its
subsequent **seen-case** regressions are recorded in the
[September 15 content review](LAUNCH_READINESS_2026-09-15.md), including failed
runs and false positives. They are separate from retrieval recall and the old
12-target visibility diagnostic. Their offline processing latency must not be
reported as real retrieval, embedding or model latency.

### Opt-in body-evidence layout experiment

`scripts/evaluate_body_evidence_ab.py` compares the unchanged report prompt
with `claim_pair_v1`: adjacent **Evidence basis** and **Local application**
paragraphs in sections 7, 11 and 12. This isolated CLI is not imported by the
application. It preserves the complete report, existing token budget, governed
quality policy and maximum two repairs; missing citations do not buy extra
model calls. It never selects or attaches citations for the model.

Use a running loopback Ollama model and an already verified, cached FastEmbed
index with local-files-only enabled (see the [CPU profile](deployment.md)).
Set `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`,
`BUSHFIRE_MODEL_MAX_TOKENS=2300`, and explicitly pin the model, temperature,
seed, index and cache paths. The experiment neither downloads models nor builds
an index. Preparation freezes the analysis and assembled passages once per
case; both arms use that same input. Run from the repository root, using new
output filenames:

```powershell
poetry run python scripts/evaluate_body_evidence_ab.py --prepare-only --scenarios data_australia/rag/body_evidence_pilot_v1.json --output output/body-pilot-prepared.json
poetry run python scripts/evaluate_body_evidence_ab.py --prepared output/body-pilot-prepared.json --run-model --max-calls 12 --output output/body-pilot-results.json
```

The two seen pilot cases permit at most 12 attempted model invocations in total.
Stop if the candidate introduces a safety failure or invalid capture, or fails
to provide a useful body-citation improvement. The separately authored four-case
holdout is not a tuning set: only proceed after freezing the candidate and an
independent source-based rubric, with at most 24 further invocations. Such a
synthetic rubric is not human/domain validation. Once inspected for tuning,
those cases become seen regression cases.

Outputs preserve first/final drafts, actual SDK evidence captures, failed arms,
budgets and provenance checks. They contain full private synthetic diagnostic
material and belong under ignored `output/`, not in a release sample. A captured
SDK request does not prove server receipt, absence of server-side truncation or
model attention. Pair completeness is only format compliance; citation coverage
and lexical overlap are not semantic accuracy. Semantic accuracy remains null,
and every artifact explicitly keeps the release gate and production use inactive.

The 2026-09-26 local seen pilot did **not** improve citations, so it stopped
before holdout generation and the candidate remains disabled. With the same
`bushfire-ready-qwen` digest `21aa9b63ebd6...`, temperature 0.2, seed 42,
2,300-token limit and frozen CPU-index inputs, the four final reports were:

| Case | Arm | Cited / requires citation | Final governed gate | Model invocations |
| --- | --- | ---: | --- | ---: |
| Cairns school | Baseline | 0 / 57 | Pass | 1 |
| Cairns school | Claim pair | 0 / 61 | Pass | 1 |
| Margaret River farm | Claim pair | 0 / 70 | Pass | 1 |
| Margaret River farm | Baseline | 0 / 53 | Pass after repair | 2 |

All final SDK captures and boundary provenance checks were valid. The farm
baseline initially triggered `premises_status_assertion`; the existing single
repair resolved that governed failure. None of the five admitted responses
contained a complete opaque citation token, including before normalization.
The candidate had zero complete pairs: school labels were absent, while farm
labels did not follow the requested plain-paragraph layout. Thus neither
canonicalization nor the pair parser explains away the missing body citations.
The four independently authored holdout cases remain unrun. These are five
local model invocations across two seen cases, not a new eight-scenario release
evaluation, cloud acceptance, semantic accuracy result or evidence that the
underlying citation problem is solved.

### Separately authorised DeepSeek comparison

`scripts/evaluate_body_evidence_deepseek.py` is a separate remote diagnostic,
not an expansion of the local-only CLI or an application setting. It accepts
only the original two-case seen-pilot prepared bundle, its externally recorded
file SHA256, and the unchanged source implementation. It does not retrieve
again, inspect the four-case holdout or edit the historical local result.

Keep an existing `DEEPSEEK_API_KEY` in the ignored local `.env` or process
environment; never put a key in command arguments or a committed artifact.
Explicitly select `LLM_PROVIDER=deepseek` and
`BUSHFIRE_ALLOW_EXTERNAL_MODEL=true` for the diagnostic process. The accepted
destination is HTTPS `api.deepseek.com` (root or `/v1`); redirects, environment
proxies and SDK retries are disabled. Set the same requested temperature and
2,300-token output limit as the local run. For example, after recording and
checking the prepared-file hash independently:

```powershell
poetry run python scripts/evaluate_body_evidence_deepseek.py --prepared output/body-pilot-prepared.json --expected-prepared-file-sha256 <recorded-sha256> --run-model --allow-external-deepseek --model deepseek-v4-flash --max-calls 12 --output output/body-deepseek-results.json
```

The example model name follows this repository's configured default, not a
verified current Railway environment value or immutable provider revision.
The historical Ollama digest remains historical input provenance; it is never
relabelled as DeepSeek identity. The remote execution records its own code,
configuration and dependency provenance. There is no automatic model fallback.

This is a cross-provider comparison, not identical sampling: the shared client
sends no seed to DeepSeek and disables thinking. It requests `top_p=0.8`, but
the [provider documentation](https://api-docs.deepseek.com/guides/thinking_mode/)
describes non-thinking `top_p` as fixed at 1.0; that statement is not a
measurement of the serving backend. Unavailable immutable model identity,
usage/currency cost and semantic accuracy must remain explicitly unknown.

At most 12 new attempted invocations cover both arms and all necessary repairs.
The new result and invocation journal are created exclusively; reservations are
flushed before calls. Authentication, quota, network or timeout failures stop
the batch, with remaining arms recorded as not run. There is no automatic
resume after an interrupted or uncertain request. Only synthetic inputs and
their frozen public-source evidence are in scope. Full outputs remain private
under `output/`; this diagnostic is not a logged-in Railway acceptance test
or a reason to enable a candidate in production.

At implementation verification of `fecc9ea` on 2026-09-26, 38 dedicated synthetic tests and
the existing related regressions passed (124 together); the complete non-E2E
suite passed 2,305 tests with 7 skipped, 6 deselected and 89.64% src coverage.
The real frozen bundle passed a read-only compatibility check. Credentials were
then configured locally and the following bounded comparison was attempted.

The 2026-09-26 DeepSeek run used **four invocations** but was **not a complete
A/B comparison**:

| Case | Arm | Final report | Cited / requires citation |
| --- | --- | --- | ---: |
| Cairns school | Baseline | Governed gate and SDK capture passed | 4 / 101 |
| Cairns school | Claim pair | Failed before protocol retry was sent | Unknown |
| Margaret River farm | Claim pair | Failed before protocol retry was sent | Unknown |
| Margaret River farm | Baseline | Failed before protocol retry was sent | Unknown |

The execution console recorded three `length` rejections. The experiment helper
then incorrectly applied the 18,000-character **structural-repair** cap to
`protocol_retry`, which replays the original full request in the production
workflow. It blocked retries of 28,319 / 25,496 / 24,206 characters without
issuing them. The artifact's `valid=true` records stable execution provenance,
not completion of the comparison or evidence that the candidate failed all
permitted production attempts. Its three unavailable reports remain failures
in the four-arm denominator, not zero-citation reports.

The helper now applies this cap only to `structural_repair`. Six new SDK-mock
cases cover long protocol retries for both arms, including exhaustion of the
unchanged three-attempt budget and actual request/capture binding. The existing
oversized structural-repair rejection remains tested. Production code, the
2,300-token limit and the original result/journal were not changed. The fix
passed 130 related tests and the full non-E2E suite: 2,311 passed, 7 skipped,
6 deselected, 89.64% src coverage. No paid rerun followed this fix. The original prepared bundle is source-bound and now
fails source-identity admission; do not rewrite its hashes or delete its
journal to force a replay.

The one evaluable report had 97 missing citations; all four cited claims point
to RAG passages present in the captured request. The lexical diagnostic marked
all four for review because of passage-level negation/condition flags. That is
not proof that all four statements are false: source-based AI review found
directly supported details alongside scope extensions from household guidance
to a campus, and from evacuation kits to first-aid kits. This review is not a
human/domain gold label or semantic accuracy score. No candidate promotion,
holdout execution, structured-generation rollout or new release follows from
this incomplete comparison.

After the protocol-retry fix, a separately authorised run on `2c1c3da`
froze a new input bundle and completed the four-arm procedure with **seven
new invocations** (eleven across both remote runs). The old four-call result
and journal remain unchanged. Retrieval source IDs, chunk text and ordering
matched the old bundle; small dense-score differences changed the context
metadata and its hash. Both arms within the new run used exactly the same new
frozen input. This is not a byte-identical cross-run model comparison.

| Case | Arm | Outcome | Cited / requires citation | Invocations |
| --- | --- | --- | ---: | ---: |
| Cairns school | Baseline | Governed gate/capture passed | 3 / 99 | 1 |
| Cairns school | Claim pair | Passed after one length retry | 3 / 98 | 2 |
| Margaret River farm | Claim pair | Governed gate/capture passed | 3 / 106 | 1 |
| Margaret River farm | Baseline | Three length rejections; no admitted report | Unknown | 3 |

All thirteen provenance checks were stable. All three admitted final reports
had valid SDK capture. The two candidate reports each contained three complete
pairs, but their six cited claims represented only 6 of 204 claims classified as
requiring citations; 198 remained uncited. The baseline denominator still
includes its failed farm arm; its available content metrics describe only the
school report. Pair compliance, completion and whole-report citation coverage
are distinct outcomes. This seen two-case run is a limited format/completion
signal, not evidence of semantic accuracy, general model superiority or
readiness for default production activation. No additional model calls or
holdout evaluation were made within this comparison; the separate selection
probe below does not replace these results.

Independent model-assisted source review found corresponding text for the six
candidate basis statements, but also material limits: one school statement used
roof/gutter maintenance evidence in a first-aid/training section, and one farm
statement compressed a condition and omitted an alternative branch. The
available school pair had three cited claims in both arms (3/99 versus 3/98),
so the layout did not increase that case's citation count. These findings do
not constitute human gold labels or permission to suppress the review flags.

The cached QLD home-preparation text also contains counterintuitive property
maintenance wording that was still present on the
[official source page](https://www.qld.gov.au/emergency/dealing-disasters/disaster-types/bushfires/bushfire-prepare/prepare-your-home-for-bushfire-season)
when checked on 2026-09-26. The raw file and submitted sentence agree; no lost
negation was found at extraction or windowing boundaries. This is a source
quality review item, not evidence that an official-source label guarantees
correctness. The frozen corpus was not silently rewritten.

### Offline atomic-claim contract, not a generation pipeline

`scripts/atomic_claim_contract.py` is an isolated pure-function prototype.
An application-owned evidence pack is built only after validating a recorded
context assembly. A payload may contain one to three explicit claim-or-abstention
items for sections 7, 11 and 12, with a separate local proposal. It cannot
declare new source metadata or ask the application to choose a similar source.

Each claim explicitly selects a passage reference and a contiguous quotation
using Python Unicode character offsets. The quotation must match that exact
visible passage slice: no trimming, Unicode normalisation, fuzzy repair or
cross-passage splicing. Duplicate JSON keys, unknown fields, invalid spans,
wrong evidence-pack hashes and abstentions carrying hidden claims/references
are rejected. The review preview is an escaped experimental fragment, not a
complete governed report or a replacement for its fifteen sections.

This proves only structural validity and literal reference binding. Topic
relevance, preservation of conditions and semantic atomicity remain unknown;
the local proposal always needs its own review and does not inherit support
from the basis. A literal quotation can still omit a neighbouring exception.
The result explicitly records zero model calls, synthetic offline origin,
no new transport capture, unevaluated full-report coverage, null semantic
accuracy and production disabled. The production Markdown client/admission
path is unchanged; this offline component has no network adapter or UI rollout.

Verification on 2026-09-26: 54 dedicated synthetic cases passed, including
Unicode offsets, oversized integers, forged references and preview escaping.
The complete non-E2E suite passed 2,365 tests, with 7 skipped, 6 deselected and
89.64% src coverage. Independent review and Ruff/Bandit checks passed. These
results verify the offline contract, not structured model output quality.

### Independent structured selection probe

`scripts/atomic_claim_adapter.py` and
`scripts/evaluate_atomic_claim_deepseek.py` keep live structured generation
separate from the production Markdown client and the offline preview. The
provider is asked for [JSON object output](https://api-docs.deepseek.com/guides/json_mode/);
normal completion, the selection schema and reference binding are still checked
by the application. Provider JSON mode is not proof of a valid claim contract.

The wire schema, `atomic-claim-selection-v1`, asks the model to choose a
`passage_ref` and an exact `quote`, not to count characters. The application
searches only the already selected passage and derives offsets only for a
single exact occurrence, including overlapping matches. No match or multiple
matches is a failure; there is no trimming, normalisation, fuzzy matching,
cross-passage search or post-failure repair. The derived payload is then
validated by the unchanged offline contract.

SDK assistant content is retained without the Markdown cleaner. Raw content,
the derived payload, evidence pack and actual SDK invocation arguments have
separate bindings. Derived offsets are labelled as application-computed, not
model-authored. Returned model, fingerprint and token usage are provider-reported
metadata, not immutable weight identity or a currency-cost measurement. The
live envelope does not reuse the offline preview's synthetic-origin wording.
Capture attests application SDK arguments, not network bytes or provider receipt.

This initial probe permits one request for each of the same two seen cases:
at most two new calls, no automatic retry, repair, model fallback or holdout
evaluation. A fixed separate journal namespace preserves the previous eleven
remote calls and prevents a new output filename resetting this probe. Transport,
quota, authentication, timeout, tooling-boundary or journal/provenance failures
stop the batch; ordinary JSON or literal-binding failures remain failed cases.
Partial section coverage and all-abstention output are reported separately,
not counted as evidence of successful full-report generation. Production and
release activation stay off, with semantic support and condition preservation
still requiring review.

The first live selection probe on 2026-09-26 used exactly two new requests,
bringing the recorded remote total to thirteen. Both returned normal `stop`
completion and parseable JSON, but **0/2 passed the selection contract**:
both root objects contained only `type` and `items`, omitting `schema` and
`evidence_pack_sha256`. No missing field was filled in, no canonical payload
was generated, and the responses were not counted as verified quote bindings.
Six provenance checks were stable; the request, response, evidence-pack and
journal bindings were independently checked. Provider-reported usage was
3,294 input plus 735 output tokens (4,029 total); currency cost remains unknown.

The executed adapter and its failure record are preserved in `39f6c21`.
Those request instructions named the required fields but only illustrated the
nested basis shape, not the complete root JSON object. A subsequent prompt-only
clarification adds a complete root example, lists the exact root keys and
distinguishes the API's `response_format` setting from the expected response
shape. Example hashes, references and quotations are placeholders, not
preselected evidence. The strict validator is unchanged; an object containing
only `type` and `items` is still rejected. This is not proof that the incomplete
example was the sole cause or that model performance has improved.

The original response and journal remain private and unchanged. The executed
adapter passed 46 dedicated tests and related regressions (163 together),
and 2,411 non-E2E tests. With the root-example clarification and two additional
synthetic tests, the non-E2E suite passed 2,413 tests, with 7 skipped,
6 deselected and 89.64% src coverage. A final wording-only change from
"Select" to "Choose" avoided a Bandit SQL-string false positive; the final
version then passed 165 related regressions, Ruff and Bandit without suppressing
the rule. The complete suite was not repeated for that synonym. At that
checkpoint, the clarification had not been rerun against a model; the observed
live result was **0/2**. No production activation or new release followed.

A separately authorised `--root-example-follow-up` is limited to the same two
seen cases, once each. This is a fixed campaign, not an arbitrary run ID or a
budget reset. Its admission binds the original prepared-file, result and journal
hashes and the clarified system-prompt hash. Rebuilt requests must equal the
original captured requests except for that system message. A separate fixed,
exclusively created journal prevents repeated dispatch by changing output names;
the old result and counters are retained. It does not evaluate the holdout or
activate production, and failures remain in the two-case denominator.

The follow-up executed on `8ed4b7a` on 2026-09-26 used exactly two new calls:
**2/2 passed the unchanged selection contract**, with all three requested
section items present in each response. Each case contained one claim with a
uniquely matching quotation and two explicit abstentions: two claims and four
abstentions overall, not six evidence-supported sections or a complete report.
There was no automatic retry or response repair. The original 0/2 result is
unchanged; this comparison/selection sequence has now used fifteen remote calls.

All six provenance checks were stable. Offline recomputation reproduced the
raw-response and invocation hashes, derived canonical payloads, pack bindings
and journal correspondence. The same local quota database increased from two
to four calls; no prior counter or journal was reset. Both responses reported
`deepseek-flash` with the same fingerprint as the first probe, which is not an
immutable model identity. Provider-reported usage was 4,298 input plus 963
output tokens (5,261 total). The input increased by 1,004 tokens across the two
requests compared with the first probe. Currency cost and semantic accuracy
remain unknown. This is a small, seen-case format observation, not a controlled
estimate of general improvement or report accuracy.

Independent model-assisted content review found that the school claim adds
local-hazard research outside its selected quotation, although neighbouring
text in the visible passage mentions it. Literal binding therefore does not
establish that the quotation supports the whole claim. The farm claim's APZ
definition and minimum defendable-space width have corresponding text in its
quotation, but its local application still requires independent review. Both
communication-section abstentions overlook relevant general material (support
contacts or warning/Easy English resources); that material does not establish
the specific school's or farm's local needs. Training-section abstentions are
consistent with the absence of specific first-aid/training/exercise material.
These are source-based AI review observations, not human/domain gold labels or
a semantic score. The observed first-claim/two-abstention pattern also matches
the example layout; this run does not separate example influence from evidence
sufficiency. No third call was made to tune these findings away.

Before execution, 23 new synthetic follow-up tests passed as part of 188 related
regressions, followed by 2,436 non-E2E tests (7 skipped, 6 deselected; 89.64% src
coverage), independent review and Ruff/Bandit checks. The four-case holdout is
still unread and unrun. No production activation or new release follows.

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
