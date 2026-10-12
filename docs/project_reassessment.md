# Current project status

Updated 2026-10-12 with native counting of the reduced repair prompt on `bde7ee7`.
The same synthetic case now uses 5,899 input tokens, 53 fewer than before, but
still exceeds the fixed input/output/margin budget by 8 tokens. The local
executor still has no production admission issuer.
Production still uses the repair-regression stop guard and unchanged
governed-report-v12 acceptance policy. The preceding three-attempt
local campaign on `7b4d1eb` completed but all three drafts failed content
acceptance. That campaign, its separate startup failure and earlier responses
remain preserved; no new report generation, accepted sample or formal release is claimed. This page
is the single maintained status summary; each model and cloud result below is
bound to its stated source version and acceptance scope.
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
- A separate limited audience-scope advisory pairs household-to-campus
  evacuation-support wording with the final submitted source sentence. It
  neither approves applicability nor changes historical diagnostic metrics.
- Generation, revision and repair receive frozen P2 values with their period
  and geographic limits. R3/Planner cues remain distinct from external evidence;
  source descriptions and unverified cross-audience applications must be separate.
- Report/review/version bindings, hash-linked file audits, protected downloads
  and Markdown/PDF/DOCX/ZIP exports.
- Docker/Railway packaging, health checks, bounded model calls and SQLite daily
  allowance persistence. This is not a multi-user report database or distributed
  service. The shared password does not authenticate individual reviewers.

See [architecture](architecture.md), [RAG](rag.md) and
[deployment instructions](DEPLOYMENT.md) for mechanisms and constraints.

## Recorded validation

### Native count after guidance reduction (2026-10-12)

A new, single count-only campaign on `bde7ee7` measured the reduced prompt.
It used the **same synthetic form, analysis, base sections and evidence** as
the closed `5505043` campaign, not a smaller replacement case. The fixture
source was byte-identical. Independent comparison confirmed unchanged JSON
and evidence bodies, length headers and markers; the only rendered changes
were the three approved guidance edits, totaling 237 UTF-8 bytes.
Full installed manifest/layer/GGUF/template and native-file hashes were
verified again before counting.

| Same-case measurement | Original `5505043` | Reduced `bde7ee7` |
| --- | ---: | ---: |
| Rendered UTF-8 bytes | 27,785 | 27,548 |
| Measured input tokens | 5,952 | **5,899** |
| Required tokens, including 2,300 output and 1 margin | 8,253 | **8,200** |
| Excess over fixed 8,192 context | 61 | **8** |

The actual saving is **53 tokens**, not 237 tokens inferred from bytes.
The measurement succeeded, but budget acceptance remains **`exceeds`**.
No input data was truncated, reservation/margin lowered, window enlarged or
native attempt repeated to obtain a fit. These results apply to this one
explicit offline rendering and case, not general form capacity or model quality.

The new harness passed **22 guarded offline tests**. Its one native attempt
made two POSTs and five health GETs, with **zero generation calls**. Exact
UTF-8 detokenization was enforced; the reply stayed in memory, so independent
review checked the vector/payload hashes and comparison code rather than
replaying that reply. Preflight/native-with-cleanup/postflight took
8.269/12.745/3.690 seconds, **24.705 seconds total**, not report-generation time.
All 459 protected files and 30 direct-prior tree entries remained unchanged.
Cleanup records and a separate approved host check confirmed the owned process,
port 14042 and temporary key were absent. Exit code 1 is consistent with owned
Windows termination, not proof of graceful native shutdown. This campaign had
no preparation/native validation failures; the prior preparation failure is
separate and remains recorded.

Private inputs and vectors remain local and ignored. The outcome SHA-256 is
`c55e54e19d5573ad104cd0eac6f8faef20eb81198c55f10030c381797bed826a`.
Ollama was not running and was not started; the numeric server log supplied
no independent context/KV-capacity evidence. Live alias resolution, server
rendering and effective service budget remain **unknown**, with production
dispatch disabled. An 8-token excess is still an excess, not permission to
round down, omit evidence or reuse an older fitting measurement.

### Scoped request-guidance reduction (2026-10-12)

The experimental [request helper](../scripts/section_local_repair_request.py)
now omits three application-owned format reminders already covered by its
unchanged shared section protocol and scope instructions. This saves exactly
**131 system-message bytes and 106 user-message bytes**, or **237 UTF-8 bytes**
under the unchanged renderer. This is a fixed prompt edit, not a general text
compressor or a transformation of user data.

The complete analysis, base-section strings, localization, framed JSON and
submitted evidence remain byte-for-byte unchanged for the same input. All
shared guidance, section-key meanings, unique output prohibitions and
trust/safety/edit-scope boundaries remain present. Matching wording inside
analysis, prose or evidence is never removed. Envelope schemas and signatures
remain unchanged; message hashes distinguish the new prompt. Obsolete prepared
objects fail reconstruction rather than silently upgrading, and old rendered
or message-count bindings cannot validate the changed request.

The focused request/invocation/render selection passed **189 tests in 33.27
seconds**; the broader eleven-module regression passed **843 tests in 63.18
seconds**. These selections overlap and must not be added together. Its first
run recorded 842 passes and one failure: the CLI returned valid JSON and exit
zero, but the local virtual-environment launcher emitted a startup warning,
violating the unchanged empty-stderr assertion. A stdlib-only probe reproduced
that warning. The retry used the existing process-local CLI-interpreter hook
with installed, supported Python 3.12.9; pytest itself remained on 3.13.9.
No persistent configuration or assertion changed, and the failed run was kept.
One earlier formatting-only check required corrections in the new test code.
Final full-repository Ruff lint/format and Bandit checks passed. Independent
static review found no remaining issue in the bounded change.

Existing request-specific budget diagnostics already report excess and signed
headroom, so no additional budget interface or admission path was introduced.
That implementation step made **zero model/tokenizer calls**. Its 237-byte
reduction alone did not establish token savings, fit or equivalent model behavior;
the separately authorized native measurement is recorded above. The
historical 5,952-token observation and 61-token excess below remain intact for
their original input/version; they were not measurements of the reduced prompt.
Effective service budget and live identity remain unknown, and production
admission stays closed.

### Installed identity and fresh native budget (2026-10-12)

This separate, single count-only campaign is bound to `5505043`. Full SHA-256
and size checks verified the installed `bushfire-ready-qwen:latest` manifest,
every referenced layer including the **4,683,073,952-byte GGUF**, its template
and the pinned native tokenizer files. The manifest describes the Qwen2 family,
7.6B parameters and Q4_K_M quantization; its parameters specify `num_ctx=8192`.
The installed Ollama client reports 0.32.15, but host checks found no running
Ollama process or listener on 11434. No Ollama daemon was started. Installed-file
identity is verified, not live Ollama alias resolution or service rendering.

The current request/render/invocation helpers constructed one fresh synthetic
section-repair input with 40 hypothetical review notes and multibyte text.
Its rendered size is **27,785 UTF-8 bytes**, with exact prospective kwargs
bound before measurement. The actual native result is:

| Budget component | Tokens |
| --- | ---: |
| Measured rendered input | 5,952 |
| Reserved output | 2,300 |
| Margin | 1 |
| Required total | **8,253** |
| Fixed context | 8,192 |
| Excess | **61** |

The outcome is **`exceeds`**, not an execution failure or a fit. At this output
reservation and margin, input must be at most 5,891 tokens. No input was shortened,
budget increased or native request retried to obtain a pass. The earlier
3,375-token result belongs to a different closed input and cannot be reused.
Detokenization had to reproduce the complete original UTF-8 bytes exactly.
The response stayed in memory: independent review verified the stored vector,
payload hashes and enforcing code, rather than replaying that response.

There was **one native attempt, two POSTs, four health GETs and zero generation**.
Final offline harness validation passed 19 tests; one earlier fixture validation
failed because synthetic form concerns were not canonical options. Only those
labels were corrected, preserving the strict scope assertion and failure record.
Preparation review also tightened owned-process cleanup deadlines. Native work
has a 90-second limit within a 120-second native-and-cleanup acceptance cap;
startup remains capped at 60 seconds. Full file hashing is timed separately.
Observed preflight/native-with-cleanup/postflight times were
10.591/13.778/4.553 seconds, **28.922 seconds total**, not report-generation latency.

All 459 protected files and 39 entries in the directly reused prior campaign
remained unchanged. Cleanup records and a separate approved host check confirmed
the owned process, port 8916 and temporary key were absent. Native exit code 1
is consistent with intentional Windows termination, not a graceful-shutdown
claim. Raw prompts and token vectors remain local and ignored. The outcome
SHA-256 is `c6811de3677d1ae8a6786b399ab1593e2ecbeff3418a8e96cae57600136b15b5`.

The numeric server log provided no independent context/KV-capacity evidence.
Live Ollama identity, rendering equivalence and effective service budget remain
**unknown**; model dispatch stays disabled. This measurement neither issues
production admission nor validates a report's content. Next integration work
must address request-specific overflow and trusted service bindings, not treat
this count or the older fitting case as general permission to generate.

### Default-denied prepared-call executor (2026-10-12)

The separate `ControlledLocalModelExecutor.execute` path in
[model_runtime.py](../src/model_runtime.py) accepts exact prospective kwargs,
an explicit local SDK dependency and an opaque single-use admission. Its
production gate's issuer is deliberately discarded, so production cannot
admit a call. An offline plan, supplied budget flag or capability from an
isolated test gate does not change that. Ordinary `generate` behavior and the
report workflow remain unchanged; no script helper is imported into runtime.

The test gate binds a detached bounded kwargs snapshot, client identity,
endpoint and underlying HTTP client. Invalid, reused or mismatched admission
is rejected before quota acquisition or worker/transport effects. An admitted
fake call preserves exact messages and request-specific `max_tokens`, requires
a loopback endpoint with redirects and environment proxies disabled, and
configures/rechecks zero SDK retries. Existing stream deadlines, owned slot
lifetime, cleanup and normal-stop admission are reused. Failures publish no
successful capture. The existing five-field SDK message binding is unchanged;
complete kwargs/response hashes use a separate in-memory `last_call_capture`.

The final six-module run passed **367 tests in 41.50 seconds**, covering the
runtime path, model limits, evidence, response admission, section protocol and
offline invocation. Independent static review found and corrected an initial
capture-schema incompatibility; the separate binding now preserves existing
consumers. An initial test setup failed because a temporary parent directory
was absent; tests passed after creating that bounded directory, without
changing assertions or persistent environment configuration.
The configured formatting check also required ordinary wrapping/spacing
corrections in the two changed Python files; the full Ruff lint/format and
Bandit checks then passed without changing behavior or quality thresholds.

Only isolated test admission and fake SDK calls were exercised. A trusted real
authority for model identity, server rendering and effective token fit is
still absent; hashes and mock capabilities are not substitutes. Standard
client settings do not prove arbitrary custom-transport behavior. Practical
request/output limits, including a local response bound independent of provider
compliance, remain responsibilities of a future admitted production integration.
No real model/tokenizer call, automatic repair activation, new accepted report
or replacement historical evidence was produced.

### Offline invocation plan (2026-10-12)

The import-only [invocation adapter](../scripts/section_local_repair_invocation.py)
addresses two prospective-call mismatches: the production builder replaces the
system prompt, and its completion kwargs use a separate configured output cap.
The adapter starts from one revalidated rendered request and derives its exact
system/user messages and positive `max_tokens` reservation. It also binds an
explicit model selector, temperature and seed, with fixed `top_p=0.8` and
`stream=True`. These are offline projection inputs, not observed provider
settings or proof of model-alias resolution.

Every accessor rebuilds the request, rendering and complete kwargs. Kind,
output contract and attempt come from the request, not override arguments.
Only a private-input accessor returns raw kwargs; normal summaries, errors and
dictionary comparisons do not disclose prompts or the free-text model name.
Supplied kwargs are serialized once into a bounded builtin-only snapshot;
validation, comparison and the reported digest describe that same snapshot,
even if the caller subsequently changes its dictionary.
The plan cannot be used as a string prompt for the existing `generate` entry
point. It has no client, callback, SDK call, configuration lookup or persistence.

Budget assessment reuses the existing request diagnostic and the reconstructed
rendered bytes, so a supplied rendered hash must match. A matching supplied
dictionary or arithmetic result is not actual submission, native measurement,
effective admission or production acceptance. Effective budget remains
`unknown`, dispatch stays disabled, and the historical 3,375-token observation
below remains limited to its closed synthetic input. No new model/tokenizer
calls or automatic repair integration are part of this update.

Validation added **76 synthetic offline tests**. The final nine-file selection
passed **597 tests in 42.60 seconds**, including existing request, candidate,
renderer, workflow, input-validation, context-budget, runtime and evidence
checks. Full repository Ruff, formatting and Bandit passed. Independent static
review identified prompt coercion and mutable-input comparison consistency;
both were corrected and have regressions. No test or validation attempt failed
in this change. The existing CLI interpreter-selection hook was retained for
the local environment; no persistent configuration or assertion was changed.
Test counts and parameter-boundary fixtures do not establish provider support,
resolved model identity or a newly measured token budget.

### Application boundary and larger synthetic inputs (2026-10-11)

The new regression tests use self-authored form inputs and synthetic frozen
analysis, not real user reports or a representative workload sample. The
application's form byte limits, prepared-message byte caps and model token
budget are different constraints; a valid large form does not establish token
fit. Any supplied token counts in these tests are arithmetic fixtures, not new
measurements or a reuse of the closed 3,375-token result below.

The production `build_governed_messages` path selects a fixed system prompt and
strips user-prompt boundaries. The experimental section-local request has its
own system instructions that preserve undeclared sections. Forwarding only its
user content through `GovernedModelClient.generate` therefore changes the
request, even when the visible user content is unchanged. There is no new
adapter or production integration in this update. Candidate-message binding
must reject the changed request; a supplied measurement tied to the offline
messages cannot validate the production messages' budget.

Injected SDK completions exercise application-side construction and capture
only. They are not actual provider calls, a tokenizer run, an Ollama-rendering
proof or content acceptance. Effective experimental dispatch remains disabled;
the production policy, repair guard and historical evidence remain unchanged.

The new module adds **14 tests**. Its three valid form fixtures contain 2,463,
4,663 and 12,663 counted UTF-8 input bytes; the combined-input boundary cases
exercise 16,384 bytes and one byte above that limit. These are form-value sizes,
not complete prompt sizes or token counts. Expanded repair envelopes retain
the complete analysis, decoded sections and evidence; an analysis within its cap
whose assembled request exceeds the message cap is rejected without trimming.
Boundary token arithmetic uses explicitly mocked counts and never changes
effective `unknown` or dispatch-disabled status.

The final seven-file regression selection passed **491 tests in 30.04 seconds**,
including the 14 new cases and the existing request, candidate, renderer,
context-budget, form-validation and model-runtime tests. Full repository Ruff,
formatting and Bandit checks passed. The first new-test run was 13 passed / 1
failed because its expectation overlooked existing fullwidth-punctuation
normalization in ordinary U0 input; the corrected assertion still compares the
entire value, while offline repair frames retain exact-value checks. A later
441 passed / 1 failed selection exposed an existing local CLI interpreter's
startup stderr warning. The test's existing interpreter-selection hook passed
that exact case, then the final 491-test selection, using installed Python
3.12.9. No runtime code, assertion threshold, persistent environment
configuration or closed experiment was changed to resolve either failure.

### Restricted offline repair-template profile (2026-10-11)

The import-only [renderer](../scripts/section_local_repair_render.py) rebuilds
the prepared request instead of trusting an arbitrary message list, rendered
string or `renderer_verified` flag. It supports one pinned Qwen2.5 model
manifest/layer/template and the unchanged 8,192-token window. Its explicit
offline mapping uses the final system content, one final user message and an
assistant prefix, with no tools, prior assistant response or injected default
system text. Message whitespace, CRLF and Unicode remain exact; ambiguous
control delimiters and identity mismatches are rejected, not repaired.

`offline_profile_rendering_verified` describes that restricted mapping only.
The private rendered-byte accessor is separate from content-free summaries;
hashes establish consistency, not hostile-process authentication or actual
runtime measurement. The existing request-budget API remains effective
`unknown`, with dispatch and production acceptance disabled.

Version-matched [Ollama template processing](https://github.com/ollama/ollama/blob/v0.32.15/template/template.go),
[chat prompt selection](https://github.com/ollama/ollama/blob/v0.32.15/server/prompt.go)
and [chat-route defaults](https://github.com/ollama/ollama/blob/v0.32.15/server/routes.go)
provide conditional source-level context, not proof of the installed backend's
execution. Default-system injection, additional messages, renderer selection
and context fitting belong to the server path. Native token counting and exact
detokenization can measure this profile's bytes; neither operation proves
provider receipt, complete context retention or report-content acceptance.

The new renderer passed **49 offline tests** in 4.34 seconds with **97% coverage
of that script**, not whole-application coverage. The unchanged request,
candidate-contract and context-budget regression files passed **408 tests** in
24.56 seconds. Full configured lint, formatting and Bandit passed; independent
review found no actionable renderer issue. One initial sandbox test invocation
failed at temporary-directory setup/coverage cleanup; the formally approved
isolated rerun passed without changing code, permissions or acceptance rules.
These results establish the offline contract, not a physical token count.

A separate, now-closed count-only run on **`53b2147`** measured the helper's
actual final bytes for a **self-authored synthetic repair request**. Its base
capture bindings were fabricated fixtures, not prior model transport evidence.
The 15,495-byte rendered input measured **3,375 tokens**. With 2,300 reserved
output tokens and one margin token, **5,676 / 8,192** leaves **2,516 tokens**.
This is one measured offline-profile budget, not a general fit guarantee or
permission to dispatch a repair.

The separate historical control reproduced all **6,917 token IDs**, not just
their count. It contains different material: these two counts are **not** a
same-content compression or performance comparison. Both token sequences passed
the runtime's fail-closed exact UTF-8 detokenization comparison before budget
records were written. Detokenized replies were memory-only; independent review
verified persisted vectors, render hashes and all four request-payload hashes,
not a second native replay or independently saved detokenized replies.

The single attempt made **4 POSTs** (tokenize/detokenize for each input),
**5 health GETs** and **zero generation requests**. The native phase, including
owned cleanup, took **12.13 seconds**; preflight **361.56 seconds** and postflight
**353.99 seconds** were separately recorded. These are validation timings, not
report-generation latency. A pre-dispatch review corrected a timing defect that
would otherwise count postflight hashing against the native limit. The original
preparation remains unchanged; a reviewed execution binding permits exactly
the counter/test replacements. Startup remains bounded at 60 seconds and the
native/owned-cleanup phase at 120 seconds, not the entire hashing workflow.

The actual GGUF and historically pinned native binaries matched before startup;
additional installed DLLs used an explicitly observed supplementary baseline,
not invented historical attestation. Approved current-host checks confirmed the
owned process, listener and temporary key were absent. The harness reported
empty owned Jobs and unchanged **542 protected entries** plus **179,762 entries
across 29 historical trees**; independent review inspected that verification,
without repeating the entire hash scan. Most of the 123,400 files in those trees
are old pytest temporary fixtures. Nothing was deleted. A future cleanup should
separate reproducible test state from retained evidence rather than treating all
local output as disposable.

The native numeric-log extraction was empty: 8,192 is the explicit bound
profile/launch configuration, not independent observation of KV capacity or
context use. Effective Ollama request admission remains `unknown`; production
dispatch remains disabled. No report, approval, audit version, export, replacement
sample or release was produced. The closed local record is
`output/local-section-repair-profile-count-20261011-a/`; its outcome SHA-256 is
`43c77002d920f901a77ed38332154d5f63bd4b4de84bf1bcbcedd61f084a0de4`.

The first final-commit CI run on `292977a` (`38108826281`) passed all 4,297
Python 3.13 tests (16 skipped, 6 deselected; 90.58% src coverage), but the
849.38-second test run exhausted almost all of the job's 15-minute total
budget. The following v0.5.0 offline verification was cancelled at the job
deadline and v0.6.0 verification was skipped; neither gate is recorded as
completed in that run. Python 3.11, Windows, Chromium and the separate Docker
workflow passed. The bounded CI correction raises only the Ubuntu pytest job
budget to 20 minutes, matching the existing Windows/browser limits. All
matrix entries, checks, coverage thresholds and release-evidence verifications
remain required; production/request/native-count timeouts are unchanged.
The subsequent `e148432` Tests workflow (`38109782550`) and Docker workflow
(`38109782528`) passed. Python 3.13 completed in 15m17s, including both offline
release verifications; its 4,297 passing tests retained 90.58% src coverage.
This later result closes the CI deadline issue without erasing the cancelled run.

### Offline localisation and request preparation (2026-10-11)

The import-only [request helper](../scripts/section_local_repair_request.py)
extends the earlier candidate checker without joining the generation workflow.
A separate content-diagnostic API collects fixed finding codes and original
narrative character spans from the same evaluator events. Its default checks,
counts, v12 policy fingerprint and production decisions remain unchanged.
One aggregate finding may have several supporting locations; locations are not
counted as additional findings. Diagnostic size limits never truncate the
underlying checks.

The helper reconstructs the exact section renderer layout and reconciles the
diagnostic findings with the full governed assessment. Only occurrences wholly
inside model-authored prose map to section IDs. Headings, source registers,
application-owned fields, report-wide failures, missing required content and
unsupported safety diagnostics cannot justify automatic section selection.
Repeated text is located by spans, not substring guesses. Incomplete or
inconsistent diagnostics cannot yield a complete recommended scope; the actual
edit scope always remains caller-declared.

A frozen request preserves the complete analysis and all 15 decoded base
sections in reversible JSON, plus the original validated evidence context
literally once. It rejects framing collisions and oversized inputs rather than
trimming data. Only a narrow JSON escape for the fixed empty-context sentence
is supported, with a decoded-value equality check. Content-free summaries bind
the scope, localisation, inputs, exact final messages and next attempt; an
explicit private-input accessor is separate from those summaries. Candidate
checking requires those messages, analysis, existing `structural_repair`
evidence kind and the next attempt within the unchanged three-call ceiling,
before applying the previous complete-response preservation contract.

Budget arithmetic uses these newly prepared messages, not an earlier prompt.
A supplied rendered-byte hash can be checked against supplied bytes, but no
trusted relationship between those bytes and model-template rendering is
established here. Effective budget status therefore stays **unknown**, even
when supplied-count arithmetic says `fits`. Dispatch and production acceptance
remain disabled. The offline allocation caps are not a replacement for the
production repair cap or proof of model-window compatibility. No real model or
tokenizer requests, cloud acceptance run, saved report or closed-campaign replay
was performed.

Initial focused validation passed **217 content/occurrence tests** and a
separate **59 request tests**. The latter measured **90% request-module
coverage**, not src coverage. Comparing the previous `21f83ba` evaluator with
current default and diagnostic checks across **468 case variants** found exact
dictionary equality. These are synthetic compatibility checks, not report
accuracy measurements.

The pre-extraction local non-E2E run passed **4,257 tests**, with 7 platform
skips, 6 browser tests deselected and **90.45% src coverage**, in 735.82 seconds
(exit zero). Full-config lint separately detected excess function complexity;
this full-run result is not relabelled as a run after the subsequent helper
extraction. Browser and final-commit CI results are separate evidence.

After the equivalent narrative/word-budget helper extraction, **392 related
tests passed** in 36.51 seconds and all **468 parity comparisons** still matched.
The overlapping focused counts are not additive. Full configured Ruff, format,
Bandit and dependency consistency checks passed. Independent re-review confirmed
unchanged evaluation order, rules and thresholds; no lint exemption was added.

Earlier failures remain recorded: a synthetic table owner accidentally matched
the existing task grammar, and an empty-context JSON-escape test misspelled its
expected literal. Only those fixtures changed. One request-test invocation failed
at temporary-directory setup before executing test bodies; isolated temporary
directories resolved it without permission or application changes. Review also
required binding occurrence IDs to their exact raw spans and rejecting forged
non-builtin result status values; both now have adversarial tests. None of these
engineering corrections constitutes new model-content acceptance.

### Offline section-preservation contract (2026-10-11)

The import-only [section-local repair contract](../scripts/section_local_repair_contract.py)
validates supplied records; it does not generate a repair or join the application
workflow. A caller must explicitly declare a nonempty proper subset of the 15
section IDs. Existing content checks aggregate findings and do not establish
which section caused them, so scope is not inferred from a check name or word
budget. Manually declaring a scope does not prove correct localisation.

Both base and candidate must be complete strict section responses. Undeclared
decoded prose must remain exact, including whitespace and citations; no-op and
out-of-scope changes are rejected. The frozen base detaches caller-owned data,
and candidate analysis must match it. Supplied system/user messages, raw response,
rendered narrative and captured evidence must agree with their recorded hashes
and ordered attempt numbers. The recorded context must occur exactly once in
the supplied user message. These checks establish internal consistency, not
independent proof of SDK execution, provider receipt or semantic evidence use.

Every base visible passage must remain in the candidate's own validated snapshot
with the same source, chunk, rank and text. Additional passages are allowed;
earlier captures are never merged into a later one. Empty captured passage sets
can satisfy preservation vacuously but do not provide supporting evidence. The
complete candidate must also pass the current governed gate and regression
guard. No partially merged report or production-save object is returned.

The separate result contains fixed reasons, IDs and hashes, not submitted prose
or prompts. Input caps reject excess data without truncation. Even an
`offline_contract_accepted` result has unassessed token fit and remains ineligible
for model dispatch and production acceptance. This prototype adds no prompt
builder, automatic scope selection, model calls, saved reports or new release;
the closed real-model failures below remain unchanged.

Synthetic validation passed **116 tests**, including a real canonical-gate
failure-to-pass pair with nonempty cited fixture evidence. A related section,
evidence, repair-guard and policy suite passed **356 tests**. After an equivalent
budget-status constant extraction, all 116 prototype tests passed again with
**94.53% coverage of the new script**; this is not whole-application coverage,
and the overlapping test counts are not additive. Ruff, formatting, Bandit and
dependency consistency checks passed; independent review found no remaining
actionable issue.

The first focused run had four fixture failures (111 passed): one sample did
not actually fail the current gate, and one shortened evidence window selected
no passage. The fixtures were corrected without changing production checks.
The scanner's later `token_budget` false positive was resolved using an
equivalent named status constant, not an exclusion. All evidence in these new
tests is self-authored synthetic data, not a new model or provider capture.

### Repair-regression stop guard (2026-10-11)

The generation loop now compares immutable status/word-count snapshots from
successive complete, fully assessed drafts. `report-repair-guard-v1` stops on
any canonical check downgrade or increased distance from the 650–800 total-body
range or 300-word model-prose minimum. Missing, duplicate, unknown or invalid
comparison checks also stop rather than counting as improvement. It does not
rank drafts by aggregate pass counts or turn advisory citations into a hard gate.
The canonical v12 quality fingerprint, repair prompts, evidence schema and shared
three-attempt ceiling remain unchanged.

The 632 → 955-word case is covered by a synthetic offline test: the distance
increases from 18 to 155, so the second response stops the run before a third
call. A 632 → 810 change can continue if no check regresses. A non-regressing
candidate becomes the next immutable baseline; protocol retries neither reset
it nor receive extra attempts. First complete successes, zero-repair runs and
revisions with structural repair disabled retain their existing behavior.

The typed stop uses fixed, content-free explanations and reaches the application
before finalisation. It leaves an existing report unchanged and writes no new
report/audit version. Actual attempts remain visible in the trace and evaluator;
an early stop is not labelled as exhausting all three calls. Earlier responses
are not silently selected or combined with the latest evidence. Evaluation
retains its existing serialized result format, and the byte-pinned historical
experiment helper remains unchanged. This protects measurable constraints, not
semantic meaning; local section editing and successful real-model repair remain
unimplemented or unverified, respectively. No closed campaign was reopened.

The focused compatibility run passed **289 tests**; after removing an unnecessary
evaluation-format extension during independent review, **118 targeted tests**
passed. An equivalent status-ranking rewrite then passed **66 guard tests** and
resolved a password-scanner false positive without adding an exclusion. These
overlapping counts are not additive. Ruff, formatting, Bandit and installed
dependency consistency checks passed; independent review found no remaining
actionable implementation issue.

Two initial restricted test runs encountered temporary-directory permissions.
The first complete coverage run subsequently recorded **4,041 passed, 2 failed,
7 skipped, 6 deselected; 90.37% coverage**. Both failures were caused by the
validation command's runtime/audit path overrides bypassing the tests' own
temporary destinations. Removing only those child-process overrides made both
unchanged tests pass. No production or test assertion was changed for those
failures. The original log remains retained; these results do not claim a
successful full run, model-quality improvement or cloud acceptance.

A subsequent clean, final-source non-E2E run passed **4,043 tests**, with
7 platform skips, 6 browser cases deselected and **90.37% src coverage**, in
424.88 seconds (exit code zero). It used the tests' own runtime/audit isolation;
the original failed run was not relabelled or overwritten. No real model or
tokenizer calls were added. Browser and remote validation are separate results,
and successful engineering checks do not establish report-content acceptance.

### Exact repair budgets and the three-attempt content check (2026-10-10)

The only production correction in `7b4d1eb` directs length feedback from the
validated word count: expand below 650, shorten above 800, otherwise adjust or
retain. Expansion must use supplied facts and qualifications, without invented
facts or padding. The 650–800-word gate, minimum 300 model-prose words,
1,400-character feedback cap, 18,000-character repair cap and shared three-call
ceiling are unchanged, as are the v12 policy fingerprint and historical rules.
Independent review and **411 focused tests** passed, with Ruff/format checks.
An earlier test command failed before collection because it selected the global
Anaconda runner; the project virtual environment completed the tests.

Exact local tokenization bound the actual messages to the model, template and
rendered prompt, with the unchanged 6,917-token control and exact round trips.
The initial request used **5,812 input tokens**; the prepared structural repair
used **4,075**, and the protocol-repair request used **5,885**. Adding 2,300
reserved output tokens and one margin token leaves respectively **79, 1,816 and
6 tokens** within the 8,192 window. The protocol path was counted, not generated.
That six-token headroom is specific to this fixture, not a general fit guarantee.
This separate count session made six tokenize/detokenize POSTs, no generation
calls, and closed with its native process, listener and temporary secret removed.

The first live-harness startup failed before any generation or tokenizer call.
Its original failure and automatic-cleanup result remain unchanged; separately
recorded, identity-checked manual cleanup removed only its owned processes.
A harmless subprocess reproduction exposed inherited pipe writers delaying
the helper timeout and a decoding error. A fresh harness used file-backed binary
output and bounded waits instead; **73 offline harness tests** and independent
review passed. These are local diagnostic harness changes, not application
timeout or quota changes. File-read caps are not disk quotas, and the campaign's
900-second admission deadline is not an OS-level lifetime guarantee.

The fresh campaign called the production `generate_narrative_with_repairs`
workflow with the frozen **Cairns / Community workshop material** input:

| Attempt | Kind | Input / output tokens | Body words, including fixed fields | Passed / failed checks |
| --- | --- | --- | --- | --- |
| 1 | Initial | 5,812 / 604 | 632 | 24 / 3 |
| 2 | Structural repair | 4,075 / 966 | 955 | 23 / 4 |
| 3 | Structural repair | 4,055 / 1,550 | 1,326 | 23 / 4 |

All three requests finished with normal stop and closed SDK/HTTP streams.
Callbacks, SDK calls, generation HTTP requests and isolated SQLite allowance
each total **3**; total usage was **17,062 tokens**. Both actual repair requests
were counted before dispatch, using two cleaned-up native sessions and eight
tokenize/detokenize POSTs. Their input usage matched those counts. The correct
"Expand" then "Shorten" instructions were dispatched, but the generated bodies
did not converge on the word limit. Measured fit does not prove retained model
context, attention or semantic evidence use.

The initial draft failed length, local-proposal and causal checks. Both repairs
failed length, scenario coverage, focus coverage and local-proposal checks.
The final four task findings correspond to unqualified task prose, rather than
the known initial proposal-status false positive. However, the focus diagnostic
said "official information sources" was missing even though that wording occurs
in the final prose: its configured matcher accepts narrower phrases such as
"official source" and "official emergency". This is a keyword-policy result,
not proof of semantic absence; no gate was relaxed to pass this case.
Body-claim diagnostics found **0/37, 0/48 and 0/46** cited/citation-requiring
claims. The source register does not substitute for those missing body citations.
These are heuristic coverage counts, not correctness or accuracy percentages.

The completed campaign is **one content-failed campaign with three failed
drafts**, separate from the startup failure and five preserved older single-call
failures. It performed no approval, audit finalization or export. Independent
postflight review reconstructed responses, checked usage and immutable-read
SQLite counts, and rehashed 1,101 protected/historical files plus 141 directory
entries without changes. Saved cleanup and a separate current-host check
confirmed the owned service, runners, native processes, listeners and native
secrets were gone. Exit code zero means the harness closed, not that content
passed. No external model API or new cloud acceptance was involved.

The closed local evidence is retained in ignored output directories, not
published as a benchmark: `local-repair-token-count-20261010-a`, failed
`local-repair-loop-validation-20261010-a`, its separate
`local-repair-loop-recovery-20261010-a`, and completed
`local-repair-loop-validation-20261010-b`. The last request ID is
`e45cd40f-695a-4c81-9261-964be80e4a8d`. None is eligible for replay.

### Proposal-status calibration and section guidance (2026-10-10)

V12 keeps the 15-string JSON interface, the 650–800-word body limit, the minimum
300 model-prose words, frozen fields and shared three-call ceiling. Only complete
abstract proposal-status sentences can avoid the local-task finding, using a
bounded vocabulary in the applicable section. This is not a general exemption
for wording such as "unverified": tables, checklists, lists, quoted/hypothetical
contexts and appended instructions retain their checks. All causal, physical
criteria, provenance and safety checks still inspect the unchanged sentence.
The low-level evaluator defaults to its previous behavior; the current lifecycle
explicitly selects the new ruleset. V2–v11 policy identities stay readable, while
new review/export requires current reassessment and normal human review.

The prompt now allocates soft section targets from the existing feasible word
range. It aims for a 685–725-word final body when feasible; the frozen Cairns
case gives a 430–470-word model-prose target. Section targets sum to the midpoint,
are not new hard gates, and cannot justify rewriting unrelated text during a
revision. Role, action and review prose describes known limits and missing
records instead of announcing what the application will write. Missing training
frequency, qualifications, appointments and records remain unknown. Repair
feedback no longer suggests Markdown tables when the model must return JSON prose.
Historical exported guidance strings and source-extraction helpers remain intact.

An offline comparison of the unchanged v11 failed narrative reduced the local
proposal count from **16 to 13**, removing only the three complete status
descriptions. Every other content-check dictionary was identical, and the
report still failed the same three checks, including its 886-word body. Original
raw text, evidence, quality, outcome and quota files were not edited. This is a
policy comparison on already-seen text, not a new model result or acceptance.
The changed frozen-case user prompt has 26,179 characters, versus 25,581 before;
its RAG, P2, analysis and source-token payloads remain exact. Character counts
do not establish the changed request's token fit.

Final local regression passed **3,961 tests**, with 7 platform skips,
6 E2E cases deselected and **90.30% src coverage**, in 527.69 seconds. The six
separate Chromium cases passed in 53.79 seconds. Dependency consistency, Ruff,
formatting, Bandit and the installed-dependency vulnerability scan passed.
Independent review closed cross-paragraph quote/hypothetical edge cases and
confirmed that the other content and privacy checks were not weakened. Three
earlier focused prompt-validation failures are retained: stale expectations and
missing current section-purpose clauses were corrected, with the original
historical byte pins and safety/privacy assertions preserved. The long selector
enumeration emitted a 60-second diagnostic stack during the successful full run;
it continued and passed, not a terminated test or hidden failure.

The subsequent remote run on `efb0334` passed both Linux versions, Chromium
and Docker, but Windows recorded **1 failed, 3,966 passed, 1 skipped and
6 deselected** in 403.36 seconds. The six-request mocked campaign returned
`timeout` rather than completing its order/capture/quota assertions. This
failure is retained separately from the successful local run; the available
log alone does not establish why the test exceeded its deadline.

A mock-only diagnostic showed that delaying request-record persistence by
1.1 seconds is sufficient to hit the fixture's unchanged 1-second deadline
before SDK dispatch. It does not identify the original CI bottleneck. The
six-request content test now reuses the scoped logical-time/inline-completion
fixture used by drift tests, with an additional simulated slow-recording case.
All original order, capture, quota and unchanged-input assertions remain;
real threaded success, concurrency, timeout and late-worker tests remain
separate. No production code or timeout was changed. The three related test
modules passed **118 tests in 132.15 seconds**; Ruff and independent read-only
review passed. The original remote failure remains part of this record.

On `89d90a3`, the six-request regression passed remotely, but the same fixture
deadline masked a different assertion: the journal-close failure test returned
`timeout` instead of `journal_close_failed`. Windows recorded **1 failed,
3,967 passed, 1 skipped and 6 deselected** in 346.26 seconds; both Linux versions,
Chromium and Docker passed. This second failure requires checking the fixture's
semantic-versus-timing boundary across its tests, not declaring the suite green
from the first fixed case.

The follow-up explicitly opts semantic, protocol, binding and recording-failure
tests into the deterministic fixture; it is not an automatic patch for the
whole module. A lightweight native-worker success test retains the real clock,
thread, request/response capture and mocked quota callbacks without durable
recorder I/O inside its deadline. The duplicate-request test keeps a separate
native competing thread and its ownership assertions, while only the primary
completion is inline. Dedicated worker-deadline and late-worker tests remain
unchanged. The same three modules then passed **119 tests in 109.63 seconds**,
with Ruff and independent static review passing. These are test-harness changes,
not production timing changes or evidence that either CI latency cause is known.

On clean source `0f6d27f`, exact native measurement recorded **5,812 input
tokens**, 192 more than v11. With the unchanged 2,300 output reservation and
1-token margin, the total is **8,113 / 8,192**, leaving only **79**. The original
6,917-token control, token IDs and both detokenization round trips matched.
Four tokenizer requests and four health checks completed in 15.85 seconds,
with zero generation and all cleanup/preservation checks passing. This is a
fit for this exact case, not a guarantee for other inputs or proof of retention.

The new report made exactly one SDK call, one generation HTTP request and one
isolated quota charge, with zero retry or repair. It completed HTTP 200, `stop`
and the terminal stream marker, using **5,812 input + 604 output = 6,416 tokens**.
All 15 prose fields and fixed-block assembly passed. However, **24 checks passed
and 3 failed out of 27**: the model wrote **377 prose words + 255 fixed words =
632**, below the 650-word lower bound; the proposal rule recorded 5 matches;
and causal checks found one unqualified planning inference and one unsupported
effect assertion. The previous "application will add" descriptions were absent
in this response, but that does not establish general resistance to instruction
echo or overall quality improvement. The text changed, and the same already-seen
case was used, so different finding counts are not an accuracy comparison.

Read-only review of the five proposal matches found four unmet task contracts
and one remaining conservative false positive: "Candidate assembly points are
unverified proposals for local review." The current bounded subject list covers
assembly-point *criteria*, not this variant. Removing that one diagnostic alone
would not make the report pass. The two causal findings concern alert disruption
without an explicitly qualified R3 inference and a maintenance-effect assertion
without an adjacent O1 citation. There were no O1 citation tokens in the raw
model prose. The source register cannot supply missing claim-level evidence.

No accepted report, audit finalization, human approval or export was created.
Independent read-only verification matched raw SDK, received stream and
assembled-body hashes, usage and count bindings. All **88 protected items**,
**12 historical trees / 510 snapshot rows**, four earlier report trees and
their quotas remained unchanged; all five isolated report quotas retain one
call each. Identity-bound cleanup and a fresh check confirmed that the service,
runner, console and listener were gone. Historical v0.5.0/v0.6.0 verification
passed on the clean source without a dirty override. This fifth bounded local
report failure is preserved; no closed request was replayed.

These changes address specific observed failure modes. They do not establish
general semantic accuracy or turn a diagnostic match into proof of a bad claim.
The v11 observations below remain separately bound evidence.

### Application-owned section protocol (2026-10-10)

V11 requests exactly 15 nonempty JSON prose fields, rather than asking the model
to copy headings or special field markers. The application renders the canonical
headings, source register and the same four fixed P2/administrative blocks.
Malformed objects, duplicate keys, unknown citations and hidden/structural
markup fail closed; admitted prose is preserved, not filtered or repaired into
acceptance. Initial generation, revision and bounded repair share this contract.
The untyped generic runtime remains compatible with legacy Markdown requests.

The unchanged 650–800-word body budget includes application fields. A separate
300-word minimum and scenario/focus coverage use projected model prose, not
application labels or tables. Saved-body projection is an exact inverse, so
review/export cannot add missing fields or silently upgrade historical drafts.
Raw response and assembled-body hashes remain distinct. V2–v10 policy identities
and byte-pinned historical evidence/response helpers are preserved through
current-only adapters; no historical comparison fixture or failed report is
rewritten. Engineering and real-model results for this changed protocol must be
recorded separately from the following v10 evidence.

The final local non-E2E run passed **3,881 tests**, with 7 platform skips,
6 E2E cases deselected and **90.27% src coverage**, in 432.87 seconds. The two
report-workflow Chromium cases passed separately in 37.70 seconds; the remaining
four download-protection browser cases passed in 4.45 seconds. Lock and
installed dependency consistency, Ruff, formatting, Bandit and the installed
dependency vulnerability scan passed. Independent review covered production
boundaries and fixture migrations without relaxing historical assertions.

The earlier broad run had 3,452 passes, 46 failures and 146 setup errors, mainly
from old response fixtures and byte-pinned historical dependencies. The pinned
modules were restored, current-only adapters added and synthetic fixtures
migrated; old real responses stayed rejected. A separate test invocation stalled
because it did not set workspace TEMP/TMP; only its verified test processes were
stopped, and the correctly isolated rerun passed. These failures remain recorded;
none is a real-model attempt or a reason to lower acceptance criteria.

On clean source `ae26cb0`, the unchanged Cairns synthetic case compiled to
25,581 user-message characters and 487 system-message characters. RAG text, P2
basis, frozen analysis and source-token blocks remained identical. An independent
native count measured **5,620 input tokens**, 254 fewer than v10. With 2,300
reserved output tokens and a 1-token margin, the total is **7,921 / 8,192**,
leaving **271**. The original 6,917-token control and both detokenization round
trips matched exactly. Four tokenizer requests and four health checks completed
in 14.80 seconds, with zero generation, successful cleanup and unchanged
protected files. This result does not guarantee fit for other inputs.

The single new local generation completed HTTP 200, normal `stop` and the
terminal stream marker, with **5,620 input + 899 output = 6,519 tokens**. SDK,
generation HTTP and isolated quota counters each recorded exactly one call;
there was no retry or repair. All 15 JSON fields were admitted and the application
supplied the exact headings, source register and four fixed blocks. The protocol,
P2 provenance, section structure and scenario/focus checks passed in this case.

The content gate still rejected the draft: **24 passed / 3 failed / 27 checks**.
Its **631 model-prose words + 255 fixed words = 886 body words** exceeded 800;
16 local-task occurrences lacked their own proposal/confirmer qualification;
one causal assertion lacked the required basis. The prose also contains
unverified promises about workshop activity and application-added records, so
structural success must not be presented as semantic correctness. Fewer failed
check categories than v10 is not a quality-rate comparison: the policy and
generated text changed, and this is one already-seen case, not a held-out study.

No accepted report, audit finalization, approval or export was produced. Raw
response and assembled-body hashes were independently reproduced; all 85
protected items, 10 historical trees / 420 snapshot rows and three earlier report
trees remained unchanged. Each old quota and the new quota remains at one.
The service, runner and console exited; a fresh process/listener check found no
remaining owned identity or listener. Historical v0.5.0 and v0.6.0 verification
also passed on the clean source without a dirty override. A pre-execution review
fixed raw-response CRLF normalization in the new postflight reader; no old report
or historical harness was changed. Model context retention and semantic evidence
use remain unknown despite matching native and SDK input counts.

### Historical v10 application-owned fields (2026-10-10)

V10 generation expanded four exact standalone slots in sections 4, 10, 13
and 14 into frozen P2 values/basis, unconfirmed role appointments, proposed
administrative review actions and an unchecked human-review item. Templates
use validated canonical scenario/timeframe/focus IDs, never raw Planner tasks
or user instructions. Missing numeric values remain unknown rather than zero;
malformed supplied values/basis block before model access. Every proposed duty
retains its own confirmer and confirmation need.

The completed body still has a 650–800-word budget including these fields;
they do not substitute for explanatory prose. Existing source, task, causal,
word-budget and safety checks still apply. Raw SDK-response and assembled-body
hashes remain distinct. Revision projects only verified exact blocks back to
slots; review and export never insert fields into a saved report. Old records
remain readable, but an old draft lacking required fields needs regeneration
for the new contract. Historical v9 fingerprints and the shared ReportAgent
source are unchanged.

Independent review found and closed a failure-propagation gap: a model response
that guessed the complete fixed blocks without emitting slots could lose its
generation rejection at initial finalization or in evaluation scripts. The
initial workflow now stops before finalization; evaluation preserves the
specific rejection in both final and per-attempt results. New mock-response
regressions cover this case; it is not a real-model success claim.

Offline compilation of the unchanged Cairns synthetic input retained the exact
RAG text, P2 basis, analysis and source-token blocks. The first v10 candidate
had 27,063 user-prompt characters versus 27,095 previously, with 193 fixed body
words. Character counts are not token measurements; the old 5,857-token result
does not bind this changed prompt. No earlier failed report was rewritten into
a passing sample.

Final local non-E2E validation passed **3,792 tests**, with 7 platform skips,
6 E2E cases deselected and **90.22% src coverage**, in 338.28 seconds. All 6
separate mock-model Chromium cases passed in 44.11 seconds. The quality wrapper
passed lock/dependency consistency, Ruff, formatting, Bandit and the installed
dependency vulnerability scan. Independent review found no remaining executable
issue in the changed production paths and test adaptations.

The first broad run exposed 94 old-contract fixture failures; it is retained
separately from the final result. Fixtures now distinguish raw slots from
assembled reports rather than bypassing the new gate. A separate AppTest timing
diagnostic traced a 3-second timeout to Streamlit's one-time REPL warning probe
(`inspect.stack` / Windows path resolution). Only the affected test fixture
declares its non-REPL environment; the timeout, rendering assertions and production
code are unchanged. These engineering results do not certify new real-model
content or a cloud deployment.

On clean source `2c58d0c`, an independent native count measured **5,874 input
tokens**. The original 6,917-token control and both detokenization round trips
matched exactly. Input plus 2,300 output and a 1-token margin totals **8,175 /
8,192**, leaving **17 tokens**. Four tokenizer requests and four health checks
completed in 12.86 seconds with zero generation; the temporary service/key were
removed and protected inputs remained unchanged. A preceding restricted prepare
failed its read-only CIM memory check; the identical guard passed under formal
permissions, without weakening it or consuming a generation attempt.

The subsequent single local report completed HTTP 200, `stop` and the terminal
stream marker, with **5,874 input + 1,146 output = 7,020 tokens**. SDK, generation
HTTP and isolated quota counters each recorded one attempt, with no repair or
retry. All four required slots were absent, and sections 10 and 13 repeated
writing instructions instead of following the output protocol. No fixed-field
assembly was applied. The final diagnostic recorded **20 passed / 6 failed
checks**: missing checklist, missing owned blocks, an 810-word body, two omitted
available P2 facts and two omitted unknown measurements, four unqualified local
tasks, and the separate generation-slot admission failure. The two owned-field
entries are distinct checks, not two independent root causes.

The report was rejected without audit finalization or export. Raw-response and
normalized-body hashes were independently verified; all 82 protected items,
332 historical snapshot rows and both older report trees were unchanged. Old
and new quota records each remain at one. The owned service/runner were stopped
by identity, their console exited naturally, and a fresh read-only check found
no remaining owned process or port listener. Historical v0.5.0 and v0.6.0 release
verification also passed on this clean source, without a dirty override.

This establishes bounded execution and correct rejection, **not report-content
success**. Token-budget fit and usage agreement do not prove provider context
retention or semantic evidence use. This result motivated the separately
validated v11 application-owned skeleton above. The failed v10 response remains
unchanged and must not be patched into an accepted sample.

### Local context and heading follow-up (2026-10-08)

On source `72cf4ae`, a single authorised local Ollama attempt completed its
stream successfully but failed six quality checks; no accepted report, audit
or export was created. Exact rendered input was 6,917 tokens. With the unchanged
2,300-token requested output, the required 9,217 tokens exceeded the configured
8,192-token window by 1,025 before any margin. This supports neither initial
input cropping nor complete retention during generation: exact retained
evidence intervals remain unknown. The raw result and original six findings
remain unchanged; the failure is not attributed solely to context pressure.

Offline maintenance introduces **governed-report-v9** for a narrow Oxford-comma
alias in the First Aid / Training / Exercises heading. Missing, duplicate and
empty sections still fail; other safety and content checks are not weakened.
The v2–v8 manifests and fingerprints remain unchanged. Historical audits remain
readable, but new review/export requires current-policy reassessment and the
normal human-review transition, without automatically promoting an old approval.

The initial prompt removes only provably duplicated P2/source-register summaries
from a verified current analysis, with original-context fallback for incomplete
source-token coverage or values whose unknown/qualified meaning would be lost.
Canonical provenance, geography, aggregation,
unknown values and R3 qualifications remain; the recorded RAG block is preserved
byte-for-byte exactly once. Custom, sparse or unmatched legacy contexts retain
their original formatting. The new offline
[context-budget diagnostic](../scripts/assess_model_context_budget.py) binds an
exact count to the supplied messages, model, template and context size. It does
not tokenize, call a model, authenticate a caller's measurement or alter request
admission. A compacted prompt has different bytes: the old 6,917-token measurement
cannot certify its fit. Frozen-case offline compilation reduced the builder's
prompt from 32,302 to 31,343 Unicode characters (959 fewer), with unchanged RAG
bytes. The original report still fails the current content gate after the narrow
heading correction; it is not a replacement model run or accepted sample.
This offline maintenance step made no new model requests. The subsequent
tokenizer measurement is recorded below; report-content acceptance remains open.

The first full regression exposed a historical-builder dependency guard: even
a byte-equivalent default output does not permit changing that shared component's
source. The public ReportAgent source was restored, and compaction is isolated
in a private prompt-builder subclass; the pinned dependency checks are unchanged.
The earlier zero-reduction replay and unsuccessful regression attempts are
retained separately, not replaced by the corrected offline comparison.

The final local non-E2E regression passed **3,681 tests**, with 7 platform skips
and 6 E2E cases deselected, **90.13% src coverage**, in 307.84 seconds. A separate
Chromium run passed all 6 mock-model cases in 48.57 seconds. The complete quality
wrapper passed lock/dependency validation, Ruff, format, Bandit and the
known-vulnerability scan; independent targeted review found no remaining blocker.
After the final tests, all 25 protected files and 9 directory metadata entries
matched their pre-change snapshots. These are final maintained-source local
results, not a new real-model, cloud, cross-platform CI or release acceptance.

Subsequently, all four [Tests jobs](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37715562784)
and [Docker smoke](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37715562779)
passed on maintenance commit `b7ac416`. This closes its cross-platform engineering
validation, not real-report or new-release acceptance.

A separate count-only attempt verified the existing model file and used a
temporary authenticated CPU process with startup warmup disabled. The native
process exited with code 1 before any health or tokenizer HTTP request; the
observed failure was `process_identity_mismatch`. No new token count was obtained.
The owned process/listener and temporary key were removed, and all 77 protected
snapshots remained unchanged. The original native startup error was not retained,
so its cause remains unconfirmed. A separately reviewed, help-only comparison on
source `5a55a4b` then used the same temporary key file: the installed native
program failed to open its full path containing Chinese characters (exit 1),
while the ASCII relative filename displayed help successfully (exit 0). These
two parser calls used no model/service arguments; the diagnostic harness issued
zero HTTP requests. The temporary key was removed, the owned processes exited
and the protected snapshots remained unchanged. This supports a path-opening
compatibility issue in that comparison, not the unique cause of the original
failure or successful model startup. That failed attempt remains frozen. The
earlier report and its five current-policy blockers remain unchanged.

### Measured compacted-prompt budget (2026-10-09)

A separately authorised single count-only retry on source `8e7ce92` used the
relative key filename and completed successfully. The old control reproduced
all **6,917 token IDs** exactly; both old and new token sequences detokenized
back to their complete rendered prompts. The compacted prompt measured
**6,613 input tokens**, a reduction of **304 tokens**. Its message, model,
template and rendered-prompt hashes are bound to the recorded measurement.

With the unchanged 2,300-token output reservation and a 1-token margin, the
required total is **8,914**, exceeding the configured 8,192-token window by
**722**. That diagnostic result was `exceeds`, motivating a further
content-preserving reduction to at most 5,891 input tokens under the same budget.

The temporary CPU service completed 4 health requests and the fixed 4
tokenize/detokenize requests, with zero generation requests, in 15.30 seconds.
The owned process and listener exited, the temporary key was removed, and all
77 protected snapshots plus both prior diagnostic artifact trees were unchanged.
There was no timeout or observed warmup. This measures standalone tokenization
of the reconstructed prompt; it does not establish provider receipt, evidence
retention during generation, semantic use, or report-content acceptance. The
earlier failed attempt and report findings remain part of the record.

### Initial instruction compaction and content check (2026-10-09)

Current-only instruction rendering consolidates repeated section, provenance
and formatting guidance. Shared repair/revision constants, all 15 section
purposes, quality-policy fingerprints and the historical ReportAgent remain
unchanged. The frozen analysis, P2 basis, canonical source identifiers and exact
RAG text remain byte-identical; no retrieved evidence was trimmed for this change.
The builder prompt shrank from 31,343 to **27,097 characters**.

The first instruction candidate (`bef863a`) measured 5,912 input tokens and
still exceeded the reserved budget by 21; its closed measurement is preserved.
The final small follow-up (`858252a`) measured **5,857 tokens**, 756 fewer than
the prior 6,613-token prompt. The original 6,917-token control and both exact
detokenization round trips passed. With output 2,300 and margin 1, the reserved
total is **8,158 / 8,192**, leaving **34 tokens**. This proves only the stated
frozen case's measured budget; changed inputs require their own assessment.

A single local Ollama initial report then completed with HTTP 200, `stop` and
the terminal stream marker. SDK, HTTP and isolated quota counters each recorded
one attempt, with zero retries or automatic repairs. Reported usage was **5,857
input + 1,231 output = 7,088 tokens**, consistent with the preflight input count.
It passed 20 of 24 bounded checks but failed four:

- 828 authored words, above the 650–800 requirement.
- Two available P2 facts and one unknown measurement were omitted.
- 28 local task occurrences lacked their own proposal/confirmation requirements.
- Two unsupported causal-effect assertions remained.

No accepted report, audit finalization or export was created. The old and new
failures remain separate; fewer blocking categories do not establish improved
quality, especially when task-qualification findings increased from 9 to 28.
Token counts and normal stream termination do not prove semantic evidence use
or complete KV retention. The next content priority is reliable P2 inclusion
and per-task confirmation fields, rather than further shrinking this fixed input.

Full local non-E2E regression on `bef863a` passed **3,696 tests**, with 7 skips,
6 E2E cases deselected and **90.13% coverage**, in 296.56 seconds. An earlier
restricted-environment run failed two loopback-dependent startup checks; both
passed with loopback access, without application-code changes. The final
18-line instruction follow-up passed 204 focused tests and full Ruff checks.
Independent review found no remaining implementation issue in that scope.
Both historical release verifiers passed on the clean local source. Temporary
count/report services were cleaned up; the original artifacts and model files
were preserved. These results are not a new release or cloud report acceptance.

Previously recorded complete engineering baseline: `8340cb2`, governed-report-v8; 3,304 local
non-E2E tests passed with 89.99% src coverage, plus 6 separate mock-model browser
cases. [All four Tests jobs](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37599159279)
and [Docker smoke](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37599159388)
passed. Railway deployment `09ac8330-b078-4ec5-a6f5-6b16a36b09f4` succeeded
on that source and the public health endpoint returned HTTP 200 / `ok`.
The earlier validation records below retain their own dates, sources and scopes.

### Documentation and maintenance follow-up (2026-10-07)

README now separates the deployed v8 engineering baseline from the frozen
v0.6.0 release and earlier v7 report evidence. The local interview handbook was
condensed to fewer than 15,000 characters, preserving failure records and metric denominators;
it remains Git-ignored rather than a new public release artifact.

The read-only [runtime maintenance check](../scripts/check_runtime_maintenance.py)
reports effective limits and selected-day SQLite usage without model calls,
dotenv loading, quota reservation or file repair. A stopped synthetic backup /
fresh-directory restoration test checks audit ancestry, hidden head/revision
metadata, traces and all quota rows; corrupted or rolled-back candidates fail.
The parent-run maintenance/quota/audit regression passed **162 tests** in 18.37
seconds; Ruff, format and independent static review passed. This is local
recovery-contract evidence, not a cloud disaster-recovery acceptance.

Maintenance code was pushed as `39d42c5`.
[Docker smoke](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37610161411)
and all four [cross-platform Tests jobs](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37610161448)
passed. Railway deployment
`be99692c-e736-4bcd-8df6-a7296bdd2284` succeeded on that source and public health
returned HTTP 200 / `ok`; no logged-in report-generation flow was run.

Read-only Railway metadata confirms one replica and the existing 1,024-MB volume
mounted at `/data`; observed current disk usage was 0.03208 GB. DeepSeek's official
balance endpoint returned account availability without a generation request;
no credentials or account amounts are recorded.

The subsequent authenticated check used deployment
`3fd84ab0-6650-403e-bc41-cb52b1f48cd4`, source `899c9ec`. The read-only CLI
returned `ready`: cloud mode, daily ceiling 100, concurrency 1, output cap 2,300,
SDK retries 0, available selected-day SQLite usage and audit/trace/quota paths
within `/data`. The aggregate count is retained privately, not a model-success
metric or a backup-recovery result.

The service's Backups page explicitly showed **No Backups** and restricted
backup creation to Pro; this workspace currently uses Hobby. No native backup
or production restore is therefore claimed. Workspace Usage displayed a
separate Agent hard limit, but no Compute limit indicator. The limits form had
empty fields, including Agent despite its displayed limit; blank fields alone
do not prove a setting is absent. No Compute monetary ceiling or email alert
has been confirmed. No credentials, account amounts or other projects' costs
are recorded. No settings, cloud data, backups or budget amounts were changed.
See [maintenance boundaries](DEPLOYMENT.md#maintenance-checks-and-backup-recovery).

The resumed follow-up is complete as a bounded engineering change: 87 dedicated /
450 related checks, final local 3,085-test non-E2E regression (src 89.76%),
independent static review and the full quality wrapper passed. The package-only
pypdf 6.19.0 upgrade passed 242 PDF/RAG/core/sample tests and an audit of 158
dependencies with zero known vulnerabilities. Commit `4a94a1b` passed all four
Tests jobs and Docker smoke, verified historical releases offline, and deployed
successfully to Railway with public health 200 / `ok`. Earlier failures remain
recorded; the pure helper stays offline-only and is not a model-quality verdict.
See the [source-bound closure](experiments/evidence-generation.md#source-bound-ci-and-deployment-closure-2026-10-03).

| Evidence | Recorded result | What it does not establish |
| --- | --- | --- |
| v0.6.0 release, `44d0c3f` | Frozen samples and RAG/report/red-team artifacts; [release record](releases/v0.6.0.md). | Current cloud or maintained-source accuracy. |
| Pre-comparison local non-E2E suite, 2026-10-01 | 2,897 passed; 7 skipped; 6 deselected; 89.76% **src** coverage; 246.17 seconds; 59 dedicated execution-tool mock tests. | Experimental-script coverage, a new six-case browser run or domain correctness; does not replace later Windows CI failure. |
| Post-classification-repair local non-E2E suite, 2026-10-01 | 2,902 passed; 7 skipped; 6 deselected; 147.46 seconds; 64 dedicated mocks. Quality wrapper/advisory scan passed; no missing local Markdown targets. | Fresh local coverage (not remeasured), a provider rerun or content correctness. |
| CI on `f69e62f`, 2026-10-01 (Sydney) | [Windows, Python 3.11/3.13 and Chromium jobs passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36732373978); [Docker cloud smoke passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36732373773). Chromium: 6 passed, 2,813 deselected, 78.50 seconds. | Real-model accuracy, live cloud user testing or a CI result for the later comparison-preparation commit. |
| First preparation CI, `c79152c`, 2026-10-01 | Python 3.11, Chromium and Docker passed; [overall Tests failed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36798289291) because the Windows/Python 3.13 dependency audits detected six advisory entries in two locked packages. | An overall CI pass. The failure is retained, not replaced by the earlier `f69e62f` result. |
| Post-repair CI, `88746b1`, 2026-10-01 | [All Windows, Python 3.11/3.13 and Chromium jobs passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36799682192); [Docker cloud smoke passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36799682220). Chromium: 6 passed, 2,845 deselected, 82.82 seconds. | Real-model content acceptance or CI evidence for a later source change. |
| Post-repair cloud deployment, `88746b1`, 2026-10-01 | Railway deployment `3661faab-8167-41c2-a319-c7e463a3e9c7` succeeded; public health returned HTTP 200 / `ok`. Only deployment metadata and health were read. | A new logged-in generation/revision/export check or access to user records, credentials or environment values. |
| Section-purpose comparison, 2026-09-29, `e2e1f02` | Six single-attempt DeepSeek completions comparing `3a00f3c` and `f4ae47c`; no section-12 maintenance contamination in either arm. | A reproduced fix, generalisation, six quality-gate passes, subsequent proposal-guidance validation or new cloud acceptance. |
| Full eight-scenario model run, 2026-09-15, `0378229` | 7/8 governed checks passed; the suite did not pass overall. | The historical release's 8/8 cannot replace this result. |
| Synthetic cloud delivery, 2026-09-27, `cab29ea` | Generation, one targeted revision, draft-only review and four download formats checked; ZIP 14 files/13 hashes; all 13 actual cloud PDF pages inspected. | Word page-layout approval, semantic accuracy, restart/concurrency coverage or real-user feedback. |
| School cloud delivery, 2026-09-29, `2ac6774` | Real registered evidence with a synthetic school form; generation took 2 attempts, revision 1; only section 8 changed; four formats downloaded; v2 ZIP 13 files/12 hashes verified; 11 PDF pages inspected with one orphaned label. | Full content acceptance, flawless PDF layout, Word page layout, professional sign-off or new release approval. |
| Export follow-up, 2026-09-30 | The original downloaded DOCX was rendered by Microsoft Word and all 17 pages inspected. Offline same-font PDF replay reproduced the old 7/8-page label separation; fixed/new-warning preview: all 12 pages inspected. A 17-page Word preview with the warning was also checked. | A new live model run, changed cloud download hashes, semantic correctness or a replacement release sample. |
| Development source review, 2026-09-30, reference `d79162f` | All 74 school-report items reviewed, including the 64 historically requiring citations; original 5 cited / 59 missing preserved. Actual final request included 2 of 3 retrieved passages. | An independently labelled benchmark, professional approval, revised production output or a corrected accuracy/citation score. |
| Source-text and prompt-contract follow-up, 2026-09-30 to 2026-10-01 | Frozen HTML and a fresh official-page download contain the same questioned wording; no missing-prefix extraction defect was found. Final 108 targeted tests pass; normal repair fixture 17,965 characters accepted, 19,201 rejected. | Author intent, source correctness, real-model adherence or content acceptance. No model requests or corpus/index changes. |
| Offline provenance/scope comparison preparation, 2026-10-01 | Three synthetic cases, two Git-bound initial prompt builders, matching logical-input/RAG hashes; 32 dedicated tests within a 127-test related run. Prepared bundle rebuilt and hash-validated; zero model calls. | Actual SDK submissions, model content, an independent benchmark or a new release sample. |
| Separately authorised provenance/scope execution, 2026-10-01, `b4ae0cf` | Exactly six DeepSeek completions, no retry/repair/judge; submission/response bindings verified; SQLite 0→6. Household-to-campus extension occurs in baseline and is separated into a proposal in candidate. | Overall content acceptance, independent generalisation or source correctness: irrelevant/mixed citations and unsupported assembly criteria remain. |
| First execution-tool CI, `b4ae0cf`, 2026-10-01 | Linux Python 3.11/3.13, Chromium and [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36809008808); [Tests failed overall](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36809008751): Windows delayed-worker error-category assertion, 1 failed / 2,902 passed / 1 skipped / 6 deselected. | A clean cross-platform pass; the failure is separate from the six successful provider requests. |
| Execution-tool deployment, `b4ae0cf`, 2026-10-01 | Railway deployment `8c55525c-f2da-44d7-b5d6-1a22639e0d0c` succeeded; public health 200 / `ok`. | CI acceptance, logged-in business flow or report-content approval. |
| Post-classification-repair CI, `8207670`, 2026-10-01 | [All four Tests jobs passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36811502188); [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36811502187). Windows 2,908 passed / 1 skipped; Linux 3.11/3.13 each 2,893 passed / 16 skipped, src 89.91% / 89.92%; all non-E2E runs exclude 6 cases. Chromium 6 passed / 2,909 deselected. | Model-content acceptance or a merged accuracy/test denominator. Closes the earlier Windows classification failure without erasing it. |
| Repaired-source deployment, `8207670`, 2026-10-01 | Railway deployment `c1bb5a60-9fc7-4685-a23e-668af9bf041f` succeeded; public health 200 / `ok`; historical v0.5.0/v0.6.0 verified offline. | New logged-in generation/revision/export acceptance or a replacement release. |
| Source/task/criterion prompt follow-up, 2026-10-01 | Local non-E2E 2,909 passed / 7 skipped / 6 deselected; src 89.76%, 244.69 seconds. Related groups 109 + 101 passed; original repair caps and closed-campaign drift refusal retained; independent static review and quality wrapper passed. | Real-model adherence or report-content improvement: zero new model calls, no historical output/metric replacement. |
| Prompt-maintenance CI/deployment, `b74cdd8`, 2026-10-01 | [All four Tests jobs passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36821348694); [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36821348655). Windows 2,915 passed / 1 skipped; Linux each 2,900 passed / 16 skipped, src 89.91% / 89.92%; non-E2E runs exclude 6. Chromium 6 passed / 2,916 deselected. Railway deployment `9d06acfb-7d9a-43e1-88c6-fd3f89407f88` succeeded, public health 200 / `ok`. | Real-model adherence, logged-in report acceptance or domain approval. Historical release/source metrics remain separate. |
| Citation/task/criterion tool validation, 2026-10-01 | 78 dedicated offline tests; local non-E2E 2,987 passed / 7 skipped / 6 deselected, src 89.76%, 224.61 seconds; static/dependency checks and independent review passed. | Model adherence, report accuracy or passing subsequent Windows CI. |
| Separate citation/task/criterion comparison, `6bd5eb7`, 2026-10-01 | Six successful initial DeepSeek completions, no retry/repair/judge; exact SDK and response bindings verified; SQLite 6→12. Frozen 19-dimension / 38-arm AI-assisted review found a local missing-criteria/boundary improvement. | Overall citation/content success: catalogue omission, repeated unqualified proposals, synthetic provenance and excessive length remain. Governed report gate was not run. |
| First new-comparison CI/deployment, `6bd5eb7`, 2026-10-01 | [Tests failed overall](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36855441949): Windows CPU-guard test collection timed out at 20 seconds; 1 failed / 2,992 passed / 1 skipped / 6 deselected. Linux/Chromium and [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36855442012). Railway deployment `71b91f03-70a2-4ebc-bb78-12712aef57ce` succeeded, health 200 / `ok`. | A clean cross-platform result, confirmed timeout cause, new logged-in business acceptance or new release. No model campaign was reopened. |
| Windows collection follow-up, 2026-10-01 | Test-only one-process/five-case collector, unchanged 20-second limit and original assertions; 21 targeted tests passed. Full local non-E2E 2,998 passed / 7 skipped / 6 deselected, src 89.76%, 224.82 seconds; quality checks and independent static review passed. | Proven original timeout cause or new CI confirmation. Production launcher and experiment captures are unchanged. |
| Collection-source CI/deployment, `93236a8`, 2026-10-01 | CPU-preflight cases passed, but [Tests failed overall](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36861131003) on a different Windows post-return quota-drift case: timeout won instead of injected drift; 1 failed / 3,003 passed / 1 skipped / 6 deselected. Linux/Chromium and [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36861131116). Railway deployment `cb82d07b-dadb-484e-8e4d-137fa67f229f` succeeded, health 200 / `ok`. | Clean CI or a proven scheduling/disk root cause. The test's one-second real deadline competes with fault injection; production first-failure order is unchanged. |
| Post-return drift isolation, 2026-10-01 | Only seven test cases use an explicit logical-clock/inline-worker fixture; real recording/capture and strict fault-order checks remain. Author's 142-test group and parent's 163-test group passed; latter 24.77 seconds. Repository Ruff/format and independent static review passed. | A new full local coverage measurement, proven CI delay cause or new CI success. Dedicated timeout/late/concurrency tests and production limits remain unchanged. |
| Isolated-test CI/deployment, `16e6375`, 2026-10-01 | [All four Tests jobs passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36863326267); [Docker passed](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/36863326319). Windows 3,004 passed / 1 skipped / 6 deselected; Linux each 2,989 passed / 16 skipped / 6 deselected, src 89.91% / 89.92%; Chromium 6 passed / 3,005 deselected. Historical v0.5.0/v0.6.0 verified offline on clean checkout. Railway deployment `998fae23-0190-4723-9d40-dc9bf2ae135c` succeeded, health 200 / `ok`. | Proven former CI delay causes, model-content acceptance, new logged-in flow or new release. Both previous failures and all original model artifacts remain unchanged. |
| Seen selection/proposal development | Two real synthetic chains structurally valid, followed by 19 offline advisory regression cases. | Independent generalisation, semantic support or production activation. |

The [September delivery record](history/LAUNCH_READINESS_2026-09-15.md)
binds the cloud deployment, report lineage and download hashes. The
[experiment record](experiments/evidence-generation.md) keeps failed and
successful probes separate. These results have different inputs, versions and
denominators; they must not be merged into a report-accuracy percentage.

## Main Gaps

1. **Report content.** The September 29 school cloud check had 6/64 cited/citation-requiring
   claims before revision and 5/64 after it, under the heuristic diagnostic. A
   targeted revision removed household destination advice but still expanded
   `household` to `household or campus group` with the same source citation.
   The actual submitted evidence retained the household scope: visibility and
   valid attribution did not ensure appropriate use. Other fourteen sections
   stayed unchanged, not necessarily correct. The new limited advisory selects
   this archived audience-extension case in an offline replay; it does not fix
   the report text or establish general applicability. The earlier 4/93 cloud result and
   six-request synthetic comparison are separate evidence, not comparable accuracy
   scores. Prefix classification and lexical matching remain advisory.
   A subsequent AI-assisted development review covered all 74 items without
   editing that output. Its proposed handling groups identify scope statements,
   local review tasks, processed-data provenance, configured considerations and
   mixed/unsubstantiated wording; these are not corrected runtime labels or
   confirmed support. New input/wording constraints address household scope,
   data provenance and unverified effects, but the original report has not been
   rewritten or re-generated. The questioned home wording is present in both
   frozen HTML and the fresh official-page download, not introduced by the
   extractor. Its intended meaning and applicability remain unresolved; it
   must not be silently corrected or treated as verified advice.
   The subsequent six-request synthetic comparison shows a local improvement in
   household audience preservation, not an overall pass. Both arms already
   handle source contradiction and preserve the tested period/denominator limits.
   Catalogue citations still accompany unsupported or mixed local tasks, and
   all six reports supply assembly criteria without a provided basis. Synthetic
   O1/P2 framing also limits provenance claims; fixture boilerplate cannot prove
   real official-source retrieval. The frozen 24-dimension / 48-arm review is
   AI-assisted development evidence, not an accuracy denominator.
   A later shared-prompt update separates cited source descriptions, local
   confirmation tasks and established evaluation criteria, and gives section 9
   an explicit missing-evidence branch. This addresses instruction gaps without
   replacing old outputs. A separately authorised six-request comparison now
   shows an explicit missing-physical-criteria branch in two candidate reports.
   Both arms already preserve the documentary conditions in the positive
   control. The catalogue candidate omits its fact and body citation, so
   silence cannot count as better citation binding. Repeated proposal
   qualification, synthetic provenance and length remain limitations;
   no overall source-use or production-content pass is established.
2. **New-release content acceptance.** The September 29 DOCX layout gap is now
   closed by native Word rendering of that exact file. The PDF label and fixed
   language-basis warning have offline regression and visual checks; original
   cloud artifacts remain unchanged. A replacement sample still needs content
   review and acceptance bound to its own source/version. The withheld legacy
   ABS language percentage remains unknown rather than being restored.
3. **External validation.** [The pilot register](pilot_results.md) still records
   no completed external participants. Automated or synthetic runs are not user
   or domain-expert validation.
4. **Production governance.** Per-user roles, verified approval identities,
   multi-tenant persistence, central operations, accessibility and independent
   legal/licence/security reviews are outside the completed controlled-demo scope.

## Suggested Next Build Order

The existing maximum-three-attempt workflow did not resolve the frozen case.
The production guard stops measurable regressions. Separate offline helpers
now check caller-scoped candidates, locate supported model-prose occurrences
and prepare lossless requests without selecting or merging prior responses.
The restricted renderer now has one native-counted synthetic profile, not a
general request-admission implementation. Before considering activation, the
next prerequisite is binding the actual application/runtime message path to the
selected model/template and testing realistic input sizes, including explicit
over-budget rejection. Global and unsupported failures remain unlocalised;
one fitting synthetic input cannot establish general repair readiness or
context retention. Record consistency is not an execution ledger or a grant to
dispatch another request. Do not activate the prototype or run another model
campaign merely because a synthetic candidate passes its offline checks.
Calibrate coverage matchers against positive and negative examples separately,
without using broader matching to conceal length, task or citation failures.
Do not reopen closed campaigns, keep resampling this case, increase the word
limit, silently trim prose or weaken the gate to accept a response. Cloud backup/recovery,
quota/cost gaps and documentation consistency remain tracked separately.
Additional demonstrations, native Word layout checks and replacement report
samples are deferred. Their incomplete acceptance remains recorded below.
Publishing a replacement sample as accepted would still require report-specific
content and delivery validation. External stakeholder and domain review remain
separate from automated engineering tests.

### Bounded school draft: closed without acceptance

The following predeclared contract was exercised on October 7; its failed result
is recorded below, not replaced by the later offline corrections.

Use the [recorded school form](history/LAUNCH_READINESS_2026-09-15.md#record-021):
Cairns, Queensland; school administration and staff; School bushfire preparedness;
a seven-day plan; First aid training, Communication channels and Evacuation.
Do not select a map area or invent contacts, assembly places, qualifications or
exercise frequency. This differs from the broader school demo card; it is one
seen-case follow-up, not an independent generalisation benchmark.

- **Useful content is retained.** Predeclare the relevant facts from the new
  frozen P2 basis and submitted passages, without choosing targets to fit the
  generated output. Afterwards verify their supporting text was included in the
  final attempt and check both presence and limits in the report. If a repair
  omits supporting text, retain the target and record a context-coverage gap,
  not a model-omission error for unseen evidence. Omission is not successful
  citation correction. Retain meaningful community context,
  periods, approximate geography and unknown language measurement. Historical
  values, every retrieved passage and unrelated household details are not
  mandatory facts for a new school report.
- **Sources and local tasks are separate.** External facts, recommendations and
  established criteria need directly supporting, actually submitted text and a
  complete adjacent citation. P2 values use frozen processed-data provenance,
  not an O1 token. A household description retains its household audience;
  campus application is a separate local-review proposal. Registers, omitted
  retrieval passages, R3/Planner output and prior model prose do not supply
  external support. Do not silently correct contradictory source wording.
- **Conditions and unknowns survive.** Preserve audience, conditions, action
  objects, years, denominators and approximate boundaries. P2 is processed
  community context, not current campus population or an O1 quotation. Do not
  restore the unverified legacy language percentage/need label. Local contacts,
  venues, qualifications, frequency and unsupported physical assembly criteria
  stay subject to confirmation; supplied evidence does not establish school
  evacuation routes or destinations.
- **Every proposed task is qualified.** Each unsupported task, bullet or table
  cell, including repetitions in the action plan, starts with
  `Unverified proposal for local review:` and identifies who must confirm what.
  Another cell or general disclaimer does not qualify it. That label cannot
  legitimise unsupported causal, medical, safety or effectiveness assertions;
  remove such assertions and identify the evidence gap.
- **All 15 sections remain useful within 650–800 narrative words.** Keep bounded
  geography/evidence and school-planning context; separate priorities,
  evacuation-planning gaps and supported or missing assembly criteria. Provide
  proposed owners, internal/parent communication and inclusion, first-aid and
  training confirmation needs, and a seven-day action plan with explicit Day 1.
  Retain review requirements and the safety boundary. Property maintenance
  cannot substitute for communications or first-aid/training; do not invent
  clinical procedures, fixed drill schedules or verified venues.
- **Acceptance is report-specific.** Review the complete
  narrative, tables and checklists against these requirements using the new
  report's version, frozen inputs and final submitted-evidence capture. Existing
  diagnostics and the detached literal-target helper locate issues; they do not
  decide semantic correctness. Keep the old 74-item review and 5/64 diagnostic
  unchanged. Only after content review can that report's Markdown/PDF/DOCX/ZIP
  bindings and actual layouts be accepted for a new draft sample. A failure is
  retained, not resampled into a pass. This establishes neither domain-expert
  approval nor user validation or a new formal release.

External generation needs separate permission and an actual report-model-call
budget including automatic repairs. Both six-call campaigns remain closed.
The existing showcase builder requires local Ollama and defaults to
`examples/v<project version>`, which may already contain frozen artifacts.
Use a fresh explicit output path for a new sample; do not bypass cloud consent
or replace old artifacts.

#### October 7 result and offline corrective work

The synthetic school form ran on deployed source `1bf3286` after a same-source
Railway recovery. The former deployment was confirmed stopped, the replacement
was uniquely running, and its persisted daily count was read as zero before
submission. The observed final SDK capture is the initial attempt; this is
application-side evidence, not an independent provider receipt. No unused call
allowance was repurposed for additional samples or a revision.

**The case did not pass acceptance.** The report exceeded the predeclared
narrative budget, left repeated local tasks unqualified, supplied unsupported
physical assembly criteria and presented some planning/household material as
causal or campus advice. The processed community facts were present but their
adjacent provenance and limits were inconsistent. Valid source IDs and the old
v6 gate did not establish supported use. The contradictory maintenance wording
was retained as an unresolved source issue, not silently rewritten.

The actual ZIP's CRC, artifact hashes and original v6 report/audit bindings
verified. Standalone Markdown and DOCX matched their package entries. PDF
content and all 13 page layouts were checked, but exact standalone-versus-package
PDF binding failed because creation/modification dates and file ID differed.
That byte mismatch remains a failure even though the rendered content matched.
The original case's Word page layout was not verified. These findings are
separate from the older September Word inspection.

Offline follow-up introduces a versioned v7 content contract and a shared,
audit-clock-bound export builder. It preserves the v6 manifest/fingerprint,
historical samples, raw official source wording and closed campaign artifacts.
Current-policy organisational approval/pilot-package export requires reassessment;
historical verification or a standalone draft download is not current approval.
The new checks are limited provenance, format and selected
risk-pattern guards, not a semantic-support oracle or an accuracy benchmark.
Only the original frozen school text is used for negative replay; its minimised
audit analysis cannot be reconstructed into a fresh full lifecycle acceptance.
No new model request or cloud business-flow rerun is part of this offline work.

Final frozen-source validation passed **3,184 non-E2E tests**, with 7 skipped,
6 browser cases deselected and **89.93% src coverage** (273.98 seconds). A
separate local browser run passed all **6 E2E cases** (52.54 seconds). Both
native and authenticated-blob delivery modes downloaded actual PDF/DOCX files
whose complete bytes matched the ZIP entries after recorded review sign-off
(not a digital signature). These use local
mock model/source services, not DeepSeek, Railway or a new School acceptance.
The original frozen School Markdown SHA remained
`cb75de7fdb0966ad2ad9c39674a6abe8aa0b575fca0ad41a3cc397436188fed3`.
External Carto style requests were blocked; map/data selection assertions passed,
but public basemap rendering and native Word page layout were not validated.

Nine earlier full-validation attempts failed or were interrupted; they are not
relabelled as passes by the final run. Diagnosed stale test assumptions included
historical source guards tied to the live working tree/all imported modules,
removed UI cache seams, obsolete policy/check counts and the former acceptance
of false P2 facts before approval. Tests now isolate pinned source-guard fixtures
without weakening the actual historical guards, and preserve real current-gate
positive/negative approval cases. The interrupted coverage run was discarded
because a browser fixture was still changing. Browser tests no longer clear the
shared output directory: fresh validated per-run directories retain old evidence.

The browser preflight also exposed two genuine local-task false positives.
Whitespace is now folded only inside each extracted claim's check shadow;
original text, spans and SDK/hash bindings are untouched. One exact complete
non-directive disclaimer is excluded from local-task classification only;
appended/separate directives and all other safety/evidence checks remain active.
The restored wrapped fixture and disclaimer passed the real v7 gate. Independent
read-only review and repository lint, format, security and dependency checks
passed. Focused batches overlap and are not added to the full-suite denominator.

#### Separately authorised v7 school check: still not accepted

Source `290143a` passed [all four Tests jobs](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37585467972)
and [Docker smoke](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/37585468020).
Railway deployment `25a3d5a3-b9d3-425a-9996-89ca3c0698b0` was confirmed successful
on that source before one new synthetic school submission. This is a separate
seen-case acceptance, not a reopening of the earlier failed campaign or an
independent benchmark. The predeclared three-call allowance was exhausted:
initial generation plus two automatic repairs, with no revision or resampling.
Filtered deployment usage logs moved from daily count 1 to 4, consistent with
the final UI's attempt 3 (`structural_repair`); these are application observations,
not independently obtained provider receipts.

Report `d3859970f1b9442ca013c6a0d611319e`, version 1, recorded at
`2026-10-07T08:06:02Z`, remains **Draft / NO-GO**. The recorded v7 gate has
19 passes and 5 failures out of 24 checks. Approval and Pilot ZIP generation
remain blocked. No replacement public sample, sign-off or new release was made.

Content review separates actual defects from checker defects:

- The narrative has **1,124 words**, above the predeclared 800-word maximum.
  Eight action sentences in sections 7, 11 and 12 lack their own proposal and
  confirmation wording. Four role-function cells rely on confirmation in a
  different cell; the checker misses the `Proposed function` header/third-person
  verb pattern. Their row-level meaning does not satisfy the declared same-cell
  contract.
- Both P2 values (172,888 and 15.6%) are present. The omission codes are lexical
  false positives for `population basis is` and `older-people`; however, the
  measurement sentence still lacks its own geographic aggregation/approximation
  basis. Recognising the wording must not borrow provenance from another sentence.
- The road-status finding selects an explicit denial of verified safety or
  operational status. Three of eleven local-task findings, both missing-confirmer
  findings and the physical-criteria finding are false positives on explicit
  non-proposal wording or `responsible authority must confirm`. This does not
  remove the genuine content failures or justify loosening the safety boundary.
- The cited household summary keeps campus application separate, but broadens
  council/library enquiry scope and omits the source's flood/storm-surge/tsunami
  framing. R3-only effects remain for evidence review. Valid citation IDs and
  proposal labels are not proof of factual support.

The authenticated UI reports 2 of 3 passages submitted in the final attempt,
using 3,357 of 3,500 context characters. Its legacy visible-prose check finds
1 lexical match out of 1 RAG-cited claim, while the separate current body
diagnostic extracts 69 claims, labels 45 missing citations and requests review
of 46. The displayed cited excerpt supports the core household-enquiry paraphrase;
its negation flag is not proof of a reversed meaning. These different heuristic
denominators are not accuracy scores. The raw final SDK messages and full frozen
analysis were not independently exported/replayed; the minimised audit does not
contain them. UI capture and one displayed excerpt are narrower evidence.

Actual Markdown, PDF, DOCX and the creation audit were downloaded. The audit
record validates and its report SHA256 matches the downloaded Markdown
`0fba1c8e1dd70f75413341df757561f0d7ce0747a3efb44f1e5bdc259c519a60`.
All 12 PDF pages were rendered and inspected; no confirmed clipping, overlap
or pagination defect remained after single-page/raw-content checks corrected an
initial batched-image display finding. DOCX ZIP integrity and expected case text
also check out, but native Word layout remains unverified:
the UI helper encountered element-cache/focus failures, without modifying the
downloaded DOCX. No current cloud-head or ZIP-byte verification is claimed for
this blocked case. Original downloads, hashes, UI snapshots and the frozen
contract/result remain in ignored `output/playwright/cloud-school-v7-20261007-a/`.

#### Offline v8 corrections after the failed school check

The current policy is now `governed-report-v8`, fingerprint
`c163091ea93e1101fc6d441be68457ea06fa4e2c5c3383084670b40237404563`.
Exact v6/v7 manifests remain unchanged and readable; historical passing results
do not authorise a new current-policy approval or export. The frozen safety
module and response-admission helper retain their source bytes. A current-only
adapter recognises the complete recorded road-status denial, without excusing
appended assertions or other finding categories.

Bounded checks now recognise the observed P2 wording, responsible-authority
confirmation and role-function cells. Explicitly negated, quoted or conditional
confirmation wording has paired rejection tests; `confirm if/whether` questions
remain distinct from a discretionary confirmation duty. Same-sentence/cell
provenance and proposal requirements remain intact. This is not unrestricted
natural-language inference.

Generation, compact repair and scoped revision now share aligned content
guidance. Planner strings are topic cues, not copyable instructions; literal
task examples satisfy the same qualification check. Repair feedback maps
allowlisted structured codes to fixed corrections and bounded word counts,
without quoting failing prose. The tested maximum structured content-feedback
subsection is 1,330 characters within its 1,400-character bound; generic failure
and targeted safety instructions are additional. Total repair remains capped at 18,000 characters
and two automatic replacement attempts. Revisions still cannot use the
context-only structural replacement path.

Final local validation: **3,304 non-E2E tests passed**, 7 skipped, 6 deselected,
**89.99% src coverage**, 307.93 seconds. A separate local mock-model browser run
passed all **6 E2E cases** in 50.41 seconds. Independent static review, Ruff,
format, Bandit, lock/install checks and the dependency-advisory scan passed.
Historical v0.5.0 and v0.6.0 export verification each passed 10 artifact hashes,
explicitly as historical, not current-policy acceptance.

The first integration run failed 5 tests with 3,298 passing: two fixtures used
an artificial check name no longer eligible for repair feedback, and three new
historical-policy cases had mismatched fixture report IDs. Test data were
corrected while retaining retry/privacy/immutable-context assertions. Earlier
temporary-directory permission failures, a corrected prompt-test assertion and
the review-discovered conditional-confirmer failure remain failures, not extra
passing trials. Fresh project-local test directories avoided the temp ACL issue
without changing system permissions.

A limited offline diagnostic still finds the frozen school's 1,124 words,
12 unqualified tasks (8 sentences and 4 function cells), and missing local P2
geographic/aggregation qualifiers. Its absent full final SDK snapshot prevents
a complete replay. Original report/download hashes and the recorded v7 failed
audit remain unchanged. No new model call, cloud business-flow acceptance,
replacement sample or release is claimed. Native Word layout and a separately
authorised new content/package acceptance remain open.

### Existing development evidence and boundaries

The bounded input changes from the
[school source review](history/LAUNCH_READINESS_2026-09-15.md#record-023) are now
covered by offline contracts; a separately authorised model comparison has now
been completed without retrying or issuing new samples.
The [three-case offline preparation](experiments/evidence-generation.md#frozen-provenancescope-comparison-preparation-2026-10-01)
binds each arm's initial prompt construction to `933d26b` / `f69e62f`, with the
same logical inputs and RAG bytes. Its original prepare-only helper and frozen
questions remain unchanged; a separate bounded runner recorded six actual
submissions and paired counterexamples. The shared source/task/criterion
guidance now has offline validation and a
[separate six-request comparison](experiments/evidence-generation.md#execution-and-bounded-content-review).
The next offline helper uses explicit source/report spans and caller-declared
literal targets to avoid silently dropping absent content from review. Its
same-unit probes, visible citation observations and per-occurrence task
qualification are not semantic verdicts or production report checks. See the
[bounded content-target advisory](experiments/evidence-generation.md#explicit-report-content-target-advisory-2026-10-02).
Useful facts, citation/task separation and consistent qualification must still
be reviewed together, without rewarding omission. Any future external run needs its own
authority and bound campaign. Do not tune and resample either closed campaign
into a pass. These are seen-failure-driven synthetic development cases, not
independent labels or a semantic-accuracy benchmark. The execution-tool timeout classification now has
a local typed-deadline repair, 64 mock tests, independent static review and
passing cross-platform CI on `8207670`. This closes that engineering failure,
not the content gaps observed in the six-request comparison.
Do not reopen closed model-call campaigns. The questioned source wording remains
flagged for qualified source review. The old diagnostic remains unchanged; a
later classifier revision needs its own version and false-positive checks.
Do not attach unrelated citations to raise the current coverage number.

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

The subsequent [school delivery check](history/LAUNCH_READINESS_2026-09-15.md#record-021)
used the deployed `2ac6774` source and three recorded model attempts. Both
downloaded packages and the parent/version bindings passed the existing verifier.
The report remains a draft: source applicability, the PDF pagination finding
and unverified Word layout prevent claiming complete acceptance. Historical
samples and formal release v0.6.0 remain unchanged.

## Dependency Audit Follow-up (2026-10-01)

The first preparation CI found three advisory entries each for Tornado 6.5.8
and urllib3 2.7.0. The upstream first patched versions are
[Tornado 6.5.9](https://github.com/tornadoweb/tornado/releases/tag/v6.5.9) and
[urllib3 2.8.0](https://github.com/urllib3/urllib3/releases/tag/2.8.0).
The maintained lock now selects Tornado **6.5.10** in dev only and urllib3
**2.8.0** in the application dependencies. Both receive explicit safe lower
bounds; the handwritten requirements list also receives the urllib3 bound.
Only these two locked packages changed. No audit exception, CI threshold,
production source, SDK or frozen release artifact was changed.

Local tooling needed a separate correction: Poetry installed inside this
project's `.venv` had an older virtualenv with known advisories. Updating that
tool to 21.7.13 required python-discovery 1.6.1. Neither is added to the project
lock or deployment dependencies, and global tools were not changed. This is
not evidence that the cloud runtime contained that local toolchain finding.

Poetry lock/install checks, `pip check`, the existing full quality-check entry
point and installed-environment `pip-audit` now pass with no known vulnerabilities
reported by that scan. Forty existing network/download/mock-SDK boundary tests
pass; the prepared comparison's original SHA256 still rebuilds and validates.
The complete post-upgrade non-E2E run passed 2,838 tests (7 skipped,
6 deselected; 89.76% src coverage) in 192.65 seconds.
Independent static review found no remaining actionable dependency finding.
A clean scan is time-bound known-advisory evidence, not penetration testing or
a guarantee that the application has no vulnerabilities. Future model execution
must record the then-effective dependency identity separately from the frozen
prompt-builder commits.

## Bottom Line

Suitable for a controlled demonstration with explicit limitations, not an
operational emergency service or a fully accepted commercial release.
