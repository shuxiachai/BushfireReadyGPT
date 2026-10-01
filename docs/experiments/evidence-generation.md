# Evidence-generation experiments

> Development diagnostics only - non-production evidence-generation experiments. Recorded outcomes, failures and limits below are historical and do not enable production use.

<a id="evidence-generation-001"></a>
### Opt-in body-evidence layout experiment

`scripts/evaluate_body_evidence_ab.py` compares the unchanged report prompt
with `claim_pair_v1`: adjacent **Evidence basis** and **Local application**
paragraphs in sections 7, 11 and 12. This isolated CLI is not imported by the
application. It preserves the complete report, existing token budget, governed
quality policy and maximum two repairs; missing citations do not buy extra
model calls. It never selects or attaches citations for the model.

Use a running loopback Ollama model and an already verified, cached FastEmbed
index with local-files-only enabled (see the [CPU profile](../DEPLOYMENT.md)).
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

<a id="evidence-generation-002"></a>
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

<a id="evidence-generation-003"></a>
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

<a id="evidence-generation-004"></a>
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

<a id="evidence-generation-005"></a>
### Offline selected-quotation review

`scripts/atomic_claim_advisory.py` adds a separate advisory layer. It revalidates
the supplied wire response and evidence pack using the unchanged selection
contract. The selected quotation is the comparison boundary for a claim;
neighbouring text is shown separately for review and never fills gaps in that
quotation. Differences in content terms, numeric literals and negation or
condition markers are diagnostic observations, not semantic verdicts.

For abstentions, a small fixed topic-cue inventory exposes general material
that a reviewer may want to inspect. A cue does not establish local needs or
prove the abstention wrong; no cue does not establish that evidence is absent.
Local sufficiency, semantic support and abstention correctness remain unknown.
Local proposals require separate review, and even an item with no detected
differences is not automatically approved.

Offline replay of the two existing follow-up responses exposes the school
claim's missing selected-quote terms and the communication cues discussed above.
It also flags the farm claim's expansion of `APZ` to its full name: a useful
example of why lexical differences are not unsupported-claim verdicts. English
word forms, synonyms, abbreviations and relation changes are not resolved by
this inventory. A repeated number can refer to a different population or
predicate even when every word and number is present.

The escaped preview is an offline review fragment, not a complete report or a
new transport capture. This layer does not change the executed prompt, wire
schema, call budgets, production gate or historical model results. It performs
no retrieval or model call and does not evaluate the four-case holdout.

Verification on 2026-09-26: 17 new synthetic advisory tests passed as part of
129 related regressions; the complete non-E2E suite passed 2,453 tests, with
7 skipped, 6 deselected and 89.64% src coverage. Independent read-only review,
Ruff and Bandit passed. Reanalysis used only the already-recorded two responses;
the executed prompt, adapter, contract, runner, raw results and call journals
remain unchanged. These checks validate diagnostic behavior, not improved
generation quality or a new semantic benchmark.

<a id="evidence-generation-006"></a>
### Offline extractive-basis prototype

`scripts/extractive_basis_prototype.py` explores a different output contract:
the response selects an application-owned passage reference, rather than
writing a claim or quotation. The application copies that entire recorded
visible passage into a separate source-text panel. There is no sentence
selection, trimming, splicing or paraphrase inside this prototype. Complete
copying applies only to the recorded visible unit, not the original document;
relevance, omitted external conditions and local applicability remain unknown.

The response root contains only `items`, one for each of sections 7, 11 and 12.
Protocol identity and evidence-pack bindings belong to the application request,
not to model-authored metadata. A selected reference can coexist with local
unknowns. An empty selection means only that no unit was selected; its note is
an unverified explanation, not proof that evidence is absent. An empty list of
local unknowns means they were not listed, not that local information is known
or sufficient. Proposals remain separate and inherit no source endorsement.

The request builder, validator and escaped typed preview are pure offline
functions. The neutral instructions do not preselect a claim/abstention pattern
for the three sections. There is no scenario input, SDK client, new call budget
or production integration. Synthetic fixtures demonstrate copying and state
separation; they do not measure whether a model selects relevant material or
improves a complete report. The existing prompt, selection wire, validators,
live runners and historical results remain unchanged.

Verification on 2026-09-26: 37 synthetic prototype tests passed as part of
156 related regressions; the full non-E2E suite passed 2,490 tests, with
7 skipped, 6 deselected and 89.64% src coverage. Independent review and
Ruff/Bandit checks passed. The four reusable development fixtures cover a
direct source unit, conditions and an exception, general guidance alongside
local unknowns, and an unselected training unit. These are constructed inputs
and responses, not new model trials or the unopened four-case holdout. The
prototype verifies full-unit copying and state separation only; selection
quality, proposal quality and complete-report usefulness remain unmeasured.

<a id="evidence-generation-007"></a>
### Bounded extractive development run

The existing atomic evaluator has an explicit `extractive-development-v1`
protocol for four synthetic development cases, with region, audience and task
focus supplied as unverified scenario data. Each case includes distractor
units. `data_australia/rag/extractive_development_v1.json` fixes the inputs and
allowed-reference sets before execution; those sets remain evaluation-only
and are never sent to the model. Agreement with these sets is a development
diagnostic, not semantic accuracy or professional approval.

The protocol reuses the existing TLS client, admission checks, quota, deadline
and SDK argument capture. A content validator runs only after the unchanged
response-boundary checks and cannot replace transport metadata. Extractive
validation results use a narrow projection, not the offline prototype's
`synthetic_offline`/zero-call envelope. The input passages are synthetic even
when the response is from a real remote model.

This batch permits at most four calls, one per case, without repair or retry.
Its fixed, exclusively created journal cannot be reset by changing output or
code filenames. Ordinary protocol failures stay in the four-case denominator;
transport, authentication, quota, timeout, safety-boundary, provenance or journal
failures stop subsequent calls. Timings include the stated invocation boundary,
not a claim about pure model inference time. Historical runs, the unopened
holdout and production generation are not changed or reclassified by this run.

Execution on `535bd6b` on 2026-09-26 completed exactly four remote requests,
one per development case, without retry or repair. All four passed the
extractive contract, and all twelve section selections agreed with their
predeclared allowed-reference sets. There were **six selected units and six
empty selections**, not twelve evidence-supported sections or complete reports.
The inputs and targets are synthetic development fixtures, not independent
human/domain gold labels. These counts do not measure semantic accuracy,
real-world retrieval quality or improvement over the earlier two seen cases.

All ten provenance checks were stable. Offline recomputation reproduced the
captured SDK arguments, raw-response hashes, evidence-pack bindings, full-unit
copies, evaluation-only target comparisons and call-journal correspondence.
The same local quota database increased from four to eight calls; the remote
comparison/selection sequence has now used nineteen calls. Earlier results and
journals remain unchanged, and no additional call was made after this batch.

The requested alias was `deepseek-v4-flash`; all four responses reported
`deepseek-flash` with fingerprint `aeb56401ca74e127821c4f9126dcb669`.
That is provider-reported identity, not an immutable weights digest. Usage was
4,191 input plus 1,721 output tokens (5,912 total), including 384 cache-hit input
tokens. The case loop took 13.67 seconds including provenance and local
validation; this is not pure inference latency or a general performance claim.
Currency cost and semantic accuracy remain unknown.

The retained local, Git-ignored result
`output/extractive-development-results-20260926-a.json` has SHA-256
`6ed778f69daeb07bdacedf6e9f3fc92293709d20a428ec2cec38b55063a2651d`;
the fixed journal `output/extractive-development-v1.calls.jsonl` has SHA-256
`98dcd5cf318d388b3a887520635791f69991c8b21a7174411bf1076c95012df0`.
The original machine summary retains `manual_raw_response_review=not_performed`;
later model-assisted source review is a separate observation, not a rewritten
raw result or a human assessment.

Independent model-assisted source review found that D3's empty equipment and
training selections still propose drafting from unspecified "general guidance"
that was not supplied for those topics. Its communication proposal selects
`passage-001` but also uses a caution from unselected `passage-002`. That caution
exists in the visible catalog, but is not bound by the selected basis. Neither
an empty selection nor a valid copied unit endorses the separate proposal.
D2 retains the supplied conditions and exclusion, while D4 requests relevant
evidence before drafting. Review did not identify filled-in local names, counts
or inspection states in these four responses; that limited observation is not
a hallucination-free or safety finding. Proposal scope for empty selections and
cross-unit dependencies needs offline definition and counterexample coverage
before advancing this candidate to the unopened holdout or production.

Before execution, 32 dedicated synthetic tests passed as part of 257 related
regressions. The full non-E2E suite passed 2,522 tests, with 7 skipped,
6 deselected and 89.64% src coverage; independent review, Ruff and Bandit passed.
The four-case holdout remains unread and unrun. Production generation and the
formal v0.6.0 release evidence are unchanged.

<a id="evidence-generation-008"></a>
### Offline proposal evidence boundary

`scripts/proposal_evidence_contract.py` is a separate offline candidate, not a
revision of the executed extractive v1 protocol. It binds an application-owned
selection context for sections 7, 11 and 12 to one validated visible-evidence
pack. That context does not attest a historical model response or SDK capture.
Old v1 responses are not automatically migrated or reclassified as new passes.

When a section has no selected unit, its proposal can only be the fixed
`requires_evidence` state. The application asks for evidence to be supplied and
reviewed before drafting; no free-text proposal or dependency list is accepted
in that branch. This prevents an empty selection from carrying an instruction
to draft from unspecified general guidance through this proposal field. It
does not prove that no relevant source exists elsewhere, or validate text in
other fields or in the production report.

A selected unit permits a separate `draft_for_review` proposal, capped at 480
Unicode codepoints, with one to three unique declared references. Those must
explicitly include the selected primary reference; none is added automatically.
An unrelated primary is not justified merely by listing it. A different basis
requires an explicit application selection change or the `requires_evidence`
state, which remains available even with a selected unit.
Every referenced visible unit is copied in full into its
own review block with its identity and hash; units are not spliced into a
synthetic quotation. Declaring several references makes those dependencies
inspectable, not their combined reasoning valid. Each dependency and proposal
remains unverified; local sufficiency, semantic support and undeclared
dependencies remain unknown.

In particular, a proposal declaring A but implicitly relying on undeclared B
can still pass structural validation. So can a proposal that reverses a source
negation or assigns the same number to a different population. Synthetic
counterexamples preserve this limitation rather than claiming that reference
validation detects it. This candidate closes the empty-selection free-text
path and makes declared cross-unit dependencies visible; it does not solve
semantic grounding or establish dependency completeness.

The functions only build, validate and render an escaped review fragment.
Rendering revalidates the typed result's request, payload and reference bindings;
it does not accept an arbitrary result dictionary. This catches accidental
tampering, not an operator with arbitrary Python-memory or filesystem control.
They add no CLI, SDK invocation, retrieval, budget or production integration.
The previous prompt, dataset, adapter, runner, raw results and call journals
remain unchanged; the nineteen-call historical sequence and unopened holdout
are unaffected.

Verification on 2026-09-26: 60 new synthetic tests passed as part of 168 related
offline regressions. The full non-E2E suite passed 2,582 tests, with 7 skipped,
6 deselected and 89.64% src coverage. Independent read-only review and the
repository Ruff/Bandit checks passed. No new model request or browser E2E run
was performed. This candidate remains outside the production generation path.

<a id="evidence-generation-009"></a>
### Bounded given-basis proposal development

The explicit `proposal-development-v1` protocol in the existing atomic
evaluator exercises the unchanged proposal contract with real model responses.
It is a separate fixed campaign, not an upgrade of previous responses or a
reset of an existing call allowance. `proposal_development_v1.json` binds the
already-seen four-case synthetic catalog by file hash, and independently fixes
application primary selections and task focus before execution. The original
catalog's selection targets do not determine these choices or enter requests.

The model receives the application-provided primary references, visible units
and proposal task. This is **given-basis proposal compliance**, not a test of
model source selection, an independent holdout, a full report or a fair A/B
comparison with the earlier selection task. The twelve slots contain six null
and six non-null primaries. Diagnostics separate fixed evidence requests in
null slots, drafts versus evidence requests in non-null slots, and single- versus
multi-source declarations. Failed or unrun cases remain in the four-case and
twelve-slot denominators as unevaluated, not successful evidence requests. If
every slot requests evidence, the non-null draft count is zero out of six.

Source-based review separately checks whether D3 uses the general-publication
caution and declares its dependency, and whether D2 preserves the prerequisites
and exceptions for the actions actually proposed. Other review questions are
whether a primary is merely attached without relevance, whether outside guidance
or local facts were invented, and whether each declared unit is copied fully.
These are review questions, not machine-scored semantic gold labels. Declaring
two references cannot establish that all dependencies have been declared.

The campaign permits at most four requests, once per case, with no repair or
retry, using the existing transport, slot, timeout, quota and SDK capture.
A fixed exclusively created journal prevents a second dispatch under changed
output or configuration names. Source data, application selections, typed
request, actual SDK kwargs and raw response are bound separately and checked
for drift. The remote result contains only a narrow projection of contract
content: it does not inherit the offline preview's zero-call origin or use its
renderer. Neither production generation nor the unopened holdout is enabled.

Pre-execution verification on 2026-09-26: 35 dedicated mock tests passed as part
of 198 related regressions. The complete non-E2E suite passed 2,617 tests,
with 7 skipped, 6 deselected and 89.64% src coverage. Independent read-only
admission review and the repository Ruff/Bandit checks passed. These are
execution-readiness checks, not real-model content results.

Execution on `e15a958` on 2026-09-26 completed exactly four new requests without
repair or retry: **4/4 cases passed the proposal contract**. All six null slots
returned only `requires_evidence`; all six non-null slots returned reviewable
draft structures, five declaring one source and one declaring two. Here,
"reviewable" means structurally admitted for review, not semantically approved.
The D3 communication draft explicitly declared both the formats unit and the
general-publication caution unit. No failed or unrun case was omitted.

All ten provenance checks were stable. Offline recomputation reproduced the
SDK request and raw-response hashes, application selection, campaign and typed
request bindings, content projection and journal. Seven dependency placements
(including reuse across sections) each copy the corresponding visible unit in
full. These are not seven independently verified sources. The same local quota
database increased from eight to twelve; this remote experiment sequence now
totals twenty-three calls. Historical results and journals remain unchanged.

All responses reported `deepseek-flash` and fingerprint
`aeb56401ca74e127821c4f9126dcb669` for the requested `deepseek-v4-flash` alias;
there is no immutable weights identity. Provider-reported usage was 4,667 input
plus 566 output tokens (5,233 total), including 768 cache-hit input tokens.
The case loop took 8.01 seconds including provenance and local validation,
not pure inference time or a general report-latency measurement. Currency cost,
semantic support and dependency completeness remain unknown.

The retained Git-ignored result
`output/proposal-development-results-20260926-a.json` has SHA-256
`52b939fff9c4bb9b9389b21df153ed97899dcaec1a0c7935b02a9d75271f8198`;
the fixed `output/proposal-development-v1.calls.jsonl` journal has SHA-256
`dc20c76b6f475064a7db1130a31aa23114036f862e4b5af83d40fba04e255d14`.
Its original `manual_raw_response_review=not_performed` field is preserved;
subsequent model-assisted source observations are separate from that machine
summary and do not substitute for human/domain review.

Independent model-assisted source review did not reproduce D3's earlier
empty-selection free-text or undeclared second-unit behavior in these new
given-basis responses. This changed task does not establish a general reduction
in unsupported content. D2's equipment proposal retains inspection, recall and
the exclusion; its training proposal retains readiness and suspension, while
the access requirement appears in the communication proposal and the copied
source. Omission of that repeated sentence in section 12 alone is not sufficient
to diagnose condition loss, but neither section is a complete stand-alone
operational instruction. D1 distinguishes general arrangements from local
unknowns, and D4 returns only evidence requests. Review did not identify filled-in
local names, quantities or confirmed statuses in these four responses; this is
not a hallucination-free or safety finding. No further request, holdout use or
production activation followed this batch.

<a id="evidence-generation-010"></a>
### Offline selection-to-proposal handoff

`scripts/selection_proposal_bridge.py` connects the two existing content
contracts through pure functions, without adding a model caller or modifying
the executed protocols. It revalidates a supplied selection response against
its original typed request, checks that request against the same evidence pack,
and only then derives section primaries and builds the proposal request. Entry
snapshots isolate the caller's pack and typed request from subsequent mutation.
Invalid selection input cannot produce a downstream request; null stays null,
with no first-source default or borrowing from another section.

Only validated references and the original catalog cross into the proposal
request. The selection stage's free proposal, explanation and local-unknown
strings are not promoted to instructions, copied suggestions or local facts.
Changing those strings changes the selection/handoff digest, but does not change
the downstream task when the validated reference choices are unchanged.

The handoff binds the application case ID, pack, selection request and raw
response, derived map and proposal request. Completion requires the caller's
expected handoff digest, revalidates those bindings, and validates the proposal
against the actual derived primaries. A failed second response yields no typed
completed result or partially accepted draft. The preview revalidates the whole
chain before displaying separately copied sources and unverified proposals.
The case-context digest covers the application label only, not a full user form
or scenario.

These checks establish a recorded application association, not response-origin
attestation. Compatible raw JSON contains no proof of which request produced
it; a case ID and hashes cannot discover every cross-case text substitution.
This is an `offline_application_supplied` fragment with zero model calls, no
transport capture and unknown semantic accuracy, not two authenticated remote
calls or a complete form-to-report workflow. Tests use synthetic inputs rather
than joining historical remote outputs into a new success claim. The existing
callers, budgets, prompts, source data and historical results remain unchanged;
the remote sequence is still twenty-three calls and the holdout is unopened.

Verification on 2026-09-26: 34 new synthetic bridge tests passed as part of
185 related regressions. The full non-E2E suite passed 2,651 tests, with
7 skipped, 6 deselected and 89.64% src coverage. Independent read-only review
and the repository Ruff/Bandit checks passed. An initial pair of test failures
came from positional section lookup; tests now address the intended section ID
without relaxing the contract or expected failure. No new model or browser E2E
run was performed, and no production path was changed.

<a id="evidence-generation-011"></a>
### Bounded real selection-to-proposal chain

The fixed `selection-proposal-chain-v1` campaign uses only the already-seen D2
and D3 synthetic cases, in that order. D2 exercises prerequisites and exceptions;
D3 exercises empty choices and possible cross-unit dependencies. These are
focused development inputs, not an independent benchmark. Each case has one
selection request and, only after that succeeds, one proposal request: at most
four new SDK invocations, with no automatic retry or repair. Existing campaigns
and their call journals are not reset or reclassified.

The second request uses the actual validated first response to derive primaries
through the offline bridge. It uses the same source scenario, section focus and
catalog, not the previous given-basis campaign's manually fixed selection map.
First-stage proposals, explanations and local-unknown text are not propagated.
Both actual SDK captures retain case/scene and evidence bindings; the second
also binds the first invocation, raw response and handoff digests. The recorded
association is at the application SDK boundary, not a provider signature or
proof of the model's internal reasoning. The result does not inherit the
bridge's offline/zero-call envelope or use its offline renderer.

All two cases, four planned stages and six final section slots stay in the
denominators. A normal selection contract/length failure skips its dependent
proposal and may allow the next fixed case; a normal proposal failure fails that
case. Transport, authentication, quota, timeout, capture/binding, input drift or
journal failure stops the batch. Existing raw responses and captures survive
failure where available. A first-stage success is not a completed chain, and
skipped stages are not successful evidence requests.

A separate fixed, exclusively created journal prevents rerunning the campaign
under another output name. Source/code/settings provenance and frozen in-memory
inputs are checked around each stage and at the end. UTC quota day and usage
are checked separately from constant provenance; a date change or unavailable
quota state stops dispatch. Daily windows do not reset the campaign budget or
erase the previous day's records. The original single-stage callers, contracts,
prompts, source data and production generation remain unchanged apart from the
existing CLI's explicit dispatch into this bounded coordinator.

Pre-execution checks on 2026-09-27: 40 dedicated mock tests passed within a
single 212-test related run. The full non-E2E suite passed 2,691 tests, with
7 skipped, 6 deselected and 89.64% src coverage; independent read-only review
and repository Ruff/Bandit checks passed. Review and regression work tightened
global invalidation after drift, preserved captures on journal-close failure,
and made a Windows test read its result explicitly as UTF-8. No acceptance rule
was relaxed. An additional temporary mock-only run checked multi-source drafts
and non-null primaries returning `requires_evidence`; it is separate from the
committed test count. These checks are not real-model content results.

The first local launch on `bd4f093` stopped before dispatch with
`deepseek_credential_missing`: the new CLI branch mistakenly supplied a no-op
dotenv loader. No SDK request, campaign journal or result file was created,
and the UTC-day quota remained zero. Removing that special case restored the
existing two-flag admission followed by `load_dotenv(..., override=False)`.
Six synthetic-environment regressions cover missing authorization and existing
environment credentials; a single related run then passed 218 tests. The
configuration-only check using the normal entry path succeeded without creating
a client. This local preflight failure is not a model response or a budget reset.
After the loader fix, the complete non-E2E suite passed 2,697 tests (7 skipped,
6 deselected; 89.64% src coverage); the chain-specific group now contains 46
tests. Independent review and repository static/security checks passed again
before any real dispatch.

Execution on `986b12c` on 2026-09-27 completed exactly four new requests,
without retries or repairs. Both seen synthetic cases completed their actual
selection-to-proposal chains: **2/2 contract-valid cases, 4/4 validated stages
and 6/6 structurally evaluable final slots**. There were no failed or skipped
cases/stages. These are structural and binding results, not selection accuracy,
semantic support, independent generalisation or full-report quality.

| Actual selection and final proposal | D2 | D3 |
| --- | --- | --- |
| Primary refs for sections 7 / 11 / 12 | 001 / 002 / 002 | null / 001 / null |
| Final `draft_for_review` slots | 3, each declaring one unit | 1, declaring units 001 and 002 |
| Final `requires_evidence` slots | 0 | 2, both with null primary |

Across both cases, four non-null primaries became drafts (three single-unit,
one multi-unit); both null primaries remained fixed evidence requests. This
particular run did not exercise a non-null primary returning `requires_evidence`.
There are no target-agreement or semantic-accuracy scores for this campaign.

Parent offline recomputation and independent read-only review reconstructed
both SDK requests per case, typed validations, actual selection mappings,
handoffs and completed projections from the unchanged source and raw responses.
The original scenario/focus/catalog matched; first-stage proposal, explanation
and local-unknown text did not enter the second-stage request. All ten source,
code and settings checks were stable. The nine journal events matched four
reservations, acquired slots, consumed allowances and started SDK invocations.
The existing SQLite record for UTC 2026-09-26 remained at 12; the 2026-09-27
record moved from 0 to 4. This remote experiment sequence totals 27 invocations;
it is not a count of all model use across the project.

Separate AI-assisted source review found useful limits rather than a semantic
pass: D2 section 7 changes the source's `unless a recall is active` to `except
when a recall is active`. The exception's scope remains potentially ambiguous;
neither string alone proves an intended operational rule or a definite polarity
reversal. D2 sections 11 and 12 both retain readiness, suspension and unresolved
access conditions, but are near-duplicates with weak section-specific emphasis.
D3's first-stage null slots still propose using unspecified general guidance;
those free-text suggestions are excluded from stage two, whose corresponding
slots correctly request evidence. D3's final communication draft explicitly
declares both the accessible-format unit and the local-verification unit.
These observations are not domain-expert adjudication or a semantic benchmark.
The original machine artifact remains unchanged, including
`manual_raw_response_review=not_performed` and unknown semantic support and
dependency completeness; this separate review must not overwrite that record.

Provider-reported usage totalled 4,403 input plus 1,155 output tokens (5,558
total), including 3,584 cache-hit input tokens. Stage elapsed times totalled
9.15 seconds; the 10.27-second batch also included local checks. Neither is a
general performance or cost estimate. The requested model was
`deepseek-v4-flash`; the provider reported `deepseek-flash` and fingerprint
`aeb56401ca74e127821c4f9126dcb669`, not an immutable model digest. Currency cost
remains unknown. No further request was made after the four-call budget.

The ignored local result `output/selection-proposal-chain-results-20260927-a.json`
has SHA256 `bb84be928ee055a308cb12346bd4e0ddd456b51f0e69cc2f00ad0ba7bc21dc2f`;
`output/selection-proposal-chain-v1.calls.jsonl` has SHA256
`f7311aab094896262af3f9af780e3a0fb6f1e633f5829cc0f54cd4534d5c1fc5`.
This closed campaign did not read or run the holdout, activate production,
rerun browser/cloud delivery acceptance, or replace the v0.6.0 release evidence.

<a id="evidence-generation-012"></a>
### Offline proposal review clues

`scripts/proposal_evidence_advisory.py` adds an explicitly invoked, offline
review alongside the proposal contract; it does not change the frozen selection
or proposal prompts, bridge outputs, campaign records or production generation.
`review_proposals(raw, request)` accepts the original JSON text/bytes and the
typed request from `proposal_evidence_contract.build_request`. It revalidates
structure and references first, then binds its separate observations to the
request, raw response and evidence pack hashes. `render_advisory(raw, request)`
recomputes that review and escapes untrusted text, rather than accepting an
editable review dictionary as an authority.

The review compares English negation, condition and qualifier markers against
**each declared dependency separately**, retaining its whole visible text.
Markers in another dependency cannot cancel a difference. An `unless` or
`except` mention prompts an exception-scope check even when the proposal copies
the source verbatim. Neither observation means a condition was definitely lost
or reversed: the source itself can be ambiguous, and its other conditions may
belong to an action the proposal does not discuss.

Cross-section drafts also receive a deterministic lexical comparison. The v1
rule uses casefolded word-token sequences and `SequenceMatcher` with autojunk
disabled, requiring at least 12 tokens in each draft and a ratio of at least
0.85 for a repetition clue. This ratio is not a content-quality score. Shared
disclaimers can trigger false alarms; short repeats, paraphrases and changes of
logical scope can escape these checks. `requires_evidence` slots participate in
neither comparison and never acquire draft text from another section.

All rows still require manual review, whether clues appear or not. Semantic
support, condition preservation and dependency completeness remain unknown.
The separate output reports **zero additional calls and no new capture**, not
that an input response was originally generated offline. It does not attest a
historical SDK request or provider response. These are development diagnostics,
not an independent benchmark, a production rejection rule or evidence that the
model's generation quality has improved. Changing diagnostic rules or thresholds
requires a new diagnostic version, not rewriting the historical experiment.

An offline replay of the unchanged 2026-09-27 chain result reconstructed both
typed proposal requests and matched them to their saved SDK payloads before
running this separate advisory. D2 prompted exception-scope review in sections
7, 11 and 12; sections 11 and 12 triggered the repetition clue with 57 and 59
tokens and a lexical ratio of `0.896551724137931`. D3 had no exception or
repetition clue, and its sections 7 and 12 remained `requires_evidence`.
Shared source IDs do not exempt drafts from comparison. These are observations
on already-seen inputs, not a new model run or a measurement of diagnostic
precision/recall. The fixed threshold was not changed for this replay. No new
API request or saved model-result rewrite occurred, and the original result
SHA256 remained `bb84be928ee055a308cb12346bd4e0ddd456b51f0e69cc2f00ad0ba7bc21dc2f`.

Verification on 2026-09-27: 19 new synthetic regression cases passed within a
176-test related run. They cover removed and retained conditions, same markers
with changed scope, independent dependency comparisons, same-source duplicates,
the minimum-length boundary and ratios 0.80/0.85/0.90, shared-disclaimer false
alarms, fixed evidence requests, input tampering and escaped rendering. An
initial same-source exemption was removed rather than exempting the motivating
case. Two subsequent test defects were corrected: a missing dictionary level,
and a purported duplicate fixture whose ratio was below the unchanged threshold.
These authored development tests are not unseen evaluation labels. Independent
read-only review found no remaining actionable issue; repository Ruff checks,
format checks and Bandit completed successfully.
The final full non-E2E suite passed **2,716 tests**, with 7 skipped, 6 deselected
and **89.64% src coverage**, in 207.41 seconds. This turn did not rerun browser
E2E, cloud delivery acceptance or any model generation; the remote experiment
sequence remains at 27 calls. The added script tests do not expand the `src`
coverage measurement to include experimental scripts.

## Section-purpose prompt comparison (2026-09-29)

This separately authorised development comparison evaluates the shared prompt
guidance introduced in `f4ae47c`, against the preceding `3a00f3c` prompt. It is
not a continuation or reopening of the closed 27-call experimental sequence.
Three fixed synthetic evidence conditions are used: maintenance only, mixed
maintenance and first-aid/training, and no relevant evidence. These passages
are test fixtures, not newly retrieved official guidance or independent
held-out evaluation material.

The comparison is limited to six initial-generation requests, one per condition
and prompt version, using identical per-condition inputs and evidence. There
are no SDK retries, structural repairs or extra report-provider judging calls. Revision
and repair remain offline-tested paths, not real-model acceptance in this run.
Prompts, actual submitted requests, raw completions and call accounting must be
preserved, including failures; changing output names must not reopen the budget.

Before inspecting responses, the review questions are fixed as follows:

- Does section 12 contain unrelated property maintenance, or does maintenance
  genuinely serve an explicit training/exercise purpose, with roles or evaluation?
- Do missing evidence and local arrangements remain specific unknowns, rather
  than invented clinical procedures, credentials or fixed exercise schedules?
- Do sections 7, 11 and 12 address their own purposes without using an unrelated
  citation as a substitute for relevant content?
- Which externally grounded statements lack citations, cite a passage that does
  not support them, or have visible supporting evidence? Keep these separate from
  locally unverified proposals and statements not requiring external evidence.

Structural/lexical diagnostics are supplementary. A qualitative AI-assisted
reading against the saved passages is not domain-expert approval or a semantic
accuracy benchmark. One response per cell cannot establish statistical improvement,
and an unchanged provider model alias is not an immutable model-weight identity.
No replacement release sample or production quality threshold follows automatically.

Before remote execution, 14 dedicated offline contract tests passed. The full
non-E2E suite passed 2,737 tests, with 7 skipped, 6 deselected and 89.64% src
coverage, in 226.92 seconds. Ruff, format checks and Bandit passed, and an
independent read-only code review found no actionable issue. This validation
does not cover real responses or measure experimental-script coverage.

### Recorded execution and findings

Executed from `e2e1f02022a8066750a2a0e3bc97fa9e29a04cff` on September 29,
09:23:24–09:24:22 UTC, after explicit approval to send these synthetic payloads
to DeepSeek. An earlier command was blocked before process creation and made no
request. The fixed journal records six SDK submissions and then closes; all six
responses finished with `stop`. No retry, repair, retrieval or extra DeepSeek
judging request was made. The default local quota database was previously uninitialised, not evidence
of zero historical usage; normal request admission created it and recorded six
calls for this UTC day, exhausting the run's six-call limit. `.env` was not changed.

The requested model was `deepseek-v4-flash`; responses reported `deepseek-flash`.
This is alias metadata, not an immutable-weight attestation. Each request used
temperature 0.2, a 2,300 output-token ceiling and disabled thinking. Provider usage
totalled 28,298 tokens (18,528 input, 9,770 output). Summed governed-call elapsed
time was 54.41 seconds; the whole campaign took 58.08 seconds. These are one-run
observations, not a price calculation or a general performance comparison.

| Synthetic condition | Baseline → current observations | Cited / heuristically citation-requiring claims |
| --- | --- | --- |
| Maintenance only | Both kept maintenance out of section 12. Current listed missing procedures, credentials and schedule more explicitly, but also added an unsupported exercise recommendation without a nearby proposal qualifier. | 2/64 → 1/73 |
| Mixed maintenance and first-aid training | Both used the relevant coordinator/debrief passage in section 12. Current placed maintenance in section 7; baseline placed it in section 6. The motivating first-aid contamination was absent in both. | 2/76 → 2/61 |
| No related evidence | Baseline proposed at least one pre-season exercise and a Week 5 exercise; current explicitly asserted no schedule and retained local confirmation. Current nevertheless added an unsupported maintenance recommendation in section 7 referring to section 13, where no matching action appeared. | 0/112 → 0/84 |

The maintenance-only current response also called the synthetic passage an
official retrieval reference in its summary, while its limitations admitted
there were no real official excerpts. A valid citation token does not resolve
that source-identity contradiction. Synthetic passages reused the existing RAG
framing, so this fixture cannot isolate a production official-source labelling
defect. This remains an observed response problem, not a verified production
root cause. Genuine maintenance-related training was not tested remotely: the
mixed fixture contains a first-aid exercise, not a maintenance exercise.

The six submitted prompts, source assemblies and raw/cleaned response bindings
were checked offline. Raw capture objects precede narrative binding; replay
used the existing `bind_normalized_narrative` on an in-memory copy before the
strict snapshot validator and claim diagnostic. Original result bytes were not
rewritten. The claim counts above are conservative automated diagnostics, not
human annotations: explicit unknowns and unverified proposals must not all be
interpreted as unsupported factual errors. Lexical matches are not semantic
support. In the baseline mixed response, the maintenance sentence retained the
inspection/cleaning actions but added "not a statement of local condition";
the diagnostic flagged possible negation mismatch and no lexical match. That
flag does not itself establish that the maintenance action was negated. Its
separate training citation did receive a lexical match.

These are initial narratives, not completed production exports. Running the
unchanged governed assessment on these synthetic pre-publication narratives
blocked all six: there is no valid official-source register, and the cited
fixtures also retain raw attribution/provenance issues. Six completed requests
must not be reported as six quality-gate passes. Human/domain approval, revision,
repair and current cloud delivery were not tested in this campaign.

Independent AI-assisted qualitative review agreed that the original section-12
maintenance failure was not reproduced in either arm. It found a useful local
difference in missing-evidence handling, alongside the residual examples above;
this does not establish overall improvement or generalisation. Preserve the
current prompt correction without further tuning to these six responses. The
next content priority remains supported body claims and clear local proposal
labelling, before replacement release samples. The earlier 27-call campaign
remains closed and unchanged; these six calls are accounted for separately.

Local, ignored artifacts under `output/section-scope-comparison-20260929/`:

- `prepared.json`: SHA256 `7581b79d2be3f191049fe8ccda33fdbe734efb771780c8798c02b4d6317f0594`.
- `results.json`: SHA256 `98f14114dd45b6655a497b0879a2faa506793afd817704447299d3a303aa0460`.
- `campaign.calls.jsonl`: SHA256 `0bb3377ab0bc3caf5209878d1f28d10ef4ec5dbc4124c3a111efb678404248ff`.

The original per-call `request-01`–`request-06`, `response-01`–`response-06` and
`result-01`–`result-06` JSON files are retained alongside them. These local raw
artifacts are not published release samples; the hashes identify the preserved
run but do not give visitors access to its unpublished bytes.

## Frozen provenance/scope comparison preparation (2026-10-01)

The separate `scoped-basis-comparison-v1` development preparation uses
[`scoped_basis_comparison.py`](../../scripts/scoped_basis_comparison.py).
It has **only offline prepare and validate commands**, no remote runner, dotenv
loading, client construction or call journal. The earlier 27-call sequence and
September 29 six-call campaign remain closed. Preparing files does not authorise
new calls or assert that any model received these prompts.

Three inline synthetic cases exercise household-to-campus scope, historical P2
data with geographic/denominator limits and missing values, and questioned
source wording with independently usable narrow content and unknown local
arrangements. The passages and figures are authored fixtures, not official
excerpts, actual community statistics or an independent held-out benchmark.
They are motivated by already-seen development failures; no holdout is read.

The baseline is `933d26b`; the candidate is `f69e62f`. Each arm uses its own
Git-bound ReportAgent and full initial prompt builder, rather than inserting
candidate-derived context into the baseline. Both share the same logical form,
profile, community, rules, plan and byte-identical RAG assembly. Changed derived
contexts and prompts are recorded separately. This compares a combined input
and instruction change, not a single-variable experiment. It does not test
revision, repair, retrieval selection, production exports or cloud delivery.

Before seeing any new response, the bundle fixes per-case review questions:

- Separate narrow source descriptions from unverified cross-audience applications;
  a valid citation or proposal prefix does not prove local applicability or effects.
- Preserve P2 years, approximate aggregation, numeric denominators and unknowns;
  do not convert area statistics into school counts or R3/Planner cues into facts.
- Do not silently correct contradictory source wording or turn it into advice.
  Retain usable narrow content and useful local confirmation tasks; deleting all
  substantive content is not automatically a better result.

Future qualitative judgements must retain output spans, actual submitted
evidence spans and reasons, including partial support, insufficient evidence
and unassessable/missing output. Citation presence, lexical overlap and semantic
support/applicability remain distinct. No automatic accuracy score is defined.
One response per arm cannot establish stable improvement or generalisation;
AI-assisted reading is not domain-expert approval.

The proposed future ceiling is six initial-generation requests, one per arm
and case, with no retries, repair or extra model judging and a stop on the first
request failure. Temperature 0.2, 2,300 output tokens and disabled thinking are
planned settings, not observations. Provider/model identity, SDK submission,
usage and latency remain unobserved. Any later execution needs a separately
approved scope and a bounded, durable execution journal; the offline bundle
alone is not dispatch authority. Historical samples and production gates stay
unchanged.

The offline commands require a Git checkout containing both fixed commits;
a source ZIP cannot reconstruct the historical arm. Run `poetry run python
scripts/scoped_basis_comparison.py prepare` once, then `validate
--expected-prepared-file-sha256 <the printed SHA256>` through the same script.
Preparation exclusively creates `output/scoped-basis-comparison-v1/prepared.json`;
validation is read-only and rebuilds all frozen fields.

On 2026-10-01, preparation and validation both completed with zero model calls.
The ignored local bundle has SHA256
`6e5be79446840dba636451df8217ec79372dce0a8dde0992ad9cfdfbba2c8d7a`.
Its two arms have identical logical-input and RAG hashes in all three cases;
the default production planning assembly includes 2 / 1 / 2 synthetic passages.

| Synthetic case | Baseline / candidate initial-prompt characters |
| --- | --- |
| Household conditions and campus records | 17,974 / 18,810 |
| Historical periods, denominators and approximate area | 18,353 / 19,532 |
| Conflicting summary and narrow maintenance record | 17,838 / 18,674 |

These are prepared initial prompts, not the separate 18,000-character repair
budget, measured provider input tokens or actual submitted payloads. Future
latency and token usage must be measured separately rather than inferred here.

Independent pre-review removed a source sentence that gave away the campus
answer, made the fixtures relevant to preparedness, separated citation presence
from support, and fixed the planned stop-on-first-failure rule. Initial static
checks twice found test import-order issues. The first dedicated pytest run
then stopped in setup: Windows `git archive` transformed line endings, causing
a false source-drift finding. The script now reads original `ls-tree` / `cat-file`
blobs and separately records checkout bytes; no Git configuration or production
source was changed. Raw-blob equality and drift-rejection regressions passed.
The final related group passed **127 tests**, including **32 new dedicated
tests**, in 7.14 seconds. Independent final static review found no remaining
actionable issue; full-repository Ruff/format and Bandit checks passed. These
are offline contract results, not model-content acceptance.

The complete non-E2E run then passed **2,838 tests**, with 7 skipped and
6 deselected, **89.76% src coverage**, in 190.99 seconds. Script tests are not
included in the `src` coverage denominator. No real browser/cloud business flow,
revision/repair generation, model request or replacement sample was performed
in this preparation.

The first `c79152c` CI did not pass overall: dependency auditing detected newly
indexed advisories for the locked Tornado/urllib3 versions, although Python
3.11, Chromium and Docker jobs passed. The separate
[dependency-audit follow-up](../project_reassessment.md#dependency-audit-follow-up-2026-10-01)
updates only two project packages and local tooling, without changing the
prepared bundle or reopening a campaign. Its original SHA256 still validates.
The source commits identify prompt builders, not immutable external libraries;
any future execution must capture the effective dependency versions.
