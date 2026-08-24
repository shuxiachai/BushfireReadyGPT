# Evaluation And Runtime Observability

BushfireReadyGPT separates three different evidence questions that should not be
collapsed into one accuracy number:

1. **Engineering regression:** does the deterministic workflow, RAG, model output
   structure, governance and export chain still behave as designed?
2. **Report evidence alignment:** can externally attributable narrative claims be
   linked back to the frozen deterministic analysis or retrieved official passage?
3. **User validation:** can real reviewers understand, check and edit the report
   without mistaking it for live or authorised emergency advice?

None of these alone proves operational safety, legal fitness or factual currency.

## v0.5.0 Release Evidence Contract

The current machine-readable release evidence is:

- [`benchmarks/rag-retrieval-v0.5.0.json`](benchmarks/rag-retrieval-v0.5.0.json),
  schema `bushfire-rag-evaluation-v3`;
- [`benchmarks/report-generation-v0.5.0.json`](benchmarks/report-generation-v0.5.0.json),
  schema `bushfire-report-generation-evaluation-v3`.

Both artifacts were collected from clean source commit
`e02f07687ee2e2329fc59afb5fe1c8ea4f532646`, bind verified RAG manifest
`aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`,
and record stable start/end provenance snapshots. The RAG artifact binds
embedding model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
The report artifact binds model digest
`21aa9b63ebd65652bfda214b8012ba0d61375855a448d7396ed57a7d7fa0f8ac`
and quality policy `governed-report-v2`, fingerprint
`7c20b6fa049dc1028cc367955eb28b5434318b2d4050995cc9cf58b53a5da9d1`.

Release evaluation uses two layers of tamper detection:

1. before/after snapshots abort an active run if the question/scenario bytes,
   Git state, model identity, policy identity or RAG index identity changes;
2. offline artifact validation recomputes outcomes instead of trusting an
   aggregate `passed` field.

For RAG, every active profile must contain complete, uniquely identified
per-question rows. The validator re-aggregates question counts,
answerable/unanswerable counts, source and passage Recall@K, MRR, Top-1,
abstention and false-positive rate. `--summary-only` intentionally produces an
inactive diagnostic artifact and cannot pass the release verifier. For report
generation, the validator binds all eight declared scenarios to their rows and
recomputes the governed, evidence, safety and degradation rates.

The current RAG release gate covers structured-planning Top-8 over 73 questions
(68 answerable + 5 unanswerable): passage recall `1.0000`, MRR `0.9216`, Top-1
`0.8529`, abstention `1.0000`, average `130.36 ms`, p95 `157.49 ms`. Its separate
free-text Top-5 diagnostic covers 84 questions (68 + 16): passage recall
`0.9706`, MRR `0.8922`, Top-1 `0.8235`, abstention `1.0000`, average `131.59 ms`,
p95 `159.00 ms`.

The current report gate covers eight scenarios. Governed, structural,
evidence-binding, RAG-title-attribution, RAG-behaviour and scenario-topic rates
are all `1.0000`. Safety-violation, unsafe-live-claim, contamination and
oversized-report rates are all `0.0000`; repair rate is `0.6250`; average model
latency is `46.77 seconds`.

The report grounding heuristic remains diagnostic: grounding-review rate
`1.0000`, average support `0.9280`, citation coverage `0.2687`, citation
precision `0.8571`, numeric consistency `0.9167`, and zero jurisdiction
conflicts. These values do not establish factual correctness and are not part of
the enforced release decision.

Verify the committed artifacts, current source datasets, shared provenance,
quality policy and governed `examples/v0.5.0` sample package without contacting
Ollama or the network:

```powershell
poetry run python scripts\verify_release.py
```

Older `v0.3.0`, `v0.4.0` and summary-only retrieval artifacts remain historical
baselines. They are not silently reinterpreted as satisfying the current
artifact schemas and policy.

## Report Evidence Alignment

Every generated or revised report runs
`src/report_grounding.py::evaluate_report_grounding`. The result is stored in the
local report session record and appears under **Review & Export > Evidence
Alignment Review (heuristic)**.

The deterministic evaluator:

- extracts model-authored sentences that contain numbers, recognised source
  attribution or evidence-reporting language;
- compares them with the frozen agent-analysis snapshot, official-source metadata
  and retrieved RAG passage text;
- checks whether reported numbers appear in the frozen evidence;
- recognises retrieved source IDs, titles, agencies and bounded acronyms;
- flags references to an incompatible Australian state or territory;
- reports support, citation coverage, citation precision, numeric consistency and
  jurisdiction-conflict metrics.

The default review thresholds are:

| Metric | Threshold |
| --- | ---: |
| Evidence support rate | >= 0.80 |
| Citation coverage rate | >= 0.70 |
| Citation precision rate | >= 0.80 |
| Numeric consistency rate | 1.00 |
| Jurisdiction conflicts | 0 |

A threshold failure marks the result `review_required`; it does not block report
generation or organisational review by itself. This is deliberate: lexical
matching can miss valid paraphrases and matching words do not establish semantic
entailment. A human must open the current cited page and verify the claim.

The real-model regression script emits these metrics per scenario alongside its
governed report-quality, RAG-behaviour, attribution, safety and contamination
results:

```powershell
poetry run python scripts\evaluate_report_generation.py --output output\report-evaluation.json
```

To inspect one captured narrative and analysis snapshot without invoking a model,
create a local JSON file outside Git:

```json
{
  "narrative": "Model-authored Markdown narrative",
  "analysis": {
    "profile": {},
    "data": {},
    "community": {},
    "knowledge": {"retrieved_chunks": []}
  }
}
```

Then run:

```powershell
poetry run python scripts\evaluate_report_grounding.py --input path\to\grounding-input.json --output output\grounding-result.json
```

The detailed output contains claim text for local human review. Do not commit it
if the original report contains sensitive or identifying input.

## Anonymous Pilot Measurement

`docs/pilot_evaluation_template.json` is intentionally empty until real external
sessions run. `src/pilot_evaluation.py` validates the repository-safe record and
calculates:

- participants completing at least 7 of 8 tasks;
- median workflow time, usefulness and evidence-class understanding;
- safety-boundary and export success rates;
- facilitator intervention count;
- citation support and citation-trust measures;
- edit-extent distribution;
- unresolved Critical/High Bad Cases and regression-test linkage.

The schema accepts only anonymous participant codes, controlled categories,
booleans and bounded numbers. Unknown fields are rejected to prevent names,
contact details, free-text notes and raw transcripts from entering the committed
measurement file.

```powershell
poetry run python scripts\evaluate_pilot_results.py --input path\to\anonymous-pilot.json --output output\pilot-summary.json
```

An empty input returns `awaiting_participants`; it never turns test readiness into
a user-validation claim.

## Privacy-minimised Runtime Trace

The governance audit and runtime Trace have different purposes:

| Record | Purpose | Content boundary |
| --- | --- | --- |
| Audit | Bind a governed report, version, review state, evidence snapshot and grounding-result digest | Privacy-minimised hashes and deterministic metadata; optional sensitive payload remains disabled by default |
| Runtime Trace | Diagnose latency, stage failure, repair and grounding-review rates | Stage names, status, duration, bounded counts/rates and safe error codes only |

Trace is enabled by default for the local single-user launcher and writes one
atomic JSON record per generation or revision under `chat_history/traces/`. The
directory is ignored by Git. The **Readiness** tab aggregates success rate, P50/P95
duration, repair rate, grounding-review rate, stage latency and safe failure
codes.

The allowlist rejects attempts to store arbitrary fields or strings. Trace files
do not contain:

- prompts or model responses;
- report text or retrieved passage text;
- locations, audiences or additional context;
- reviewer identity or organisation details;
- free-text user errors or feedback.

Configuration:

```dotenv
BUSHFIRE_TRACE_ENABLED=true
# BUSHFIRE_TRACE_DIR=chat_history/traces
```

Trace is local diagnostic evidence, not central production monitoring. It has no
remote exporter, distributed context, multi-instance aggregation, automated
retention policy or access-control service. Those remain deployment work if the
application moves beyond a single-user pilot.

## Bad Case To Regression Loop

Use the same disposition loop for pilot findings, grounding flags and runtime
failures:

1. reproduce the issue with non-sensitive inputs;
2. assign an anonymous `BC-001`-style ID and severity;
3. add the smallest deterministic regression test that captures the failure;
4. implement and review the correction;
5. run the targeted test, non-E2E suite and relevant model benchmark;
6. record the test path and disposition without committing raw participant notes.

This converts observed failures into durable engineering evidence while keeping
human feedback and operational logs within their appropriate privacy boundaries.

## Local Engineering Validation

The `v0.5.0` release candidate was checked locally with `429` automated tests and
`86.08%` source coverage against the enforced `85%` minimum. Ruff, Bandit,
Poetry lock consistency, installed-package consistency and `pip-audit` all
passed; `pip-audit` reported no known vulnerabilities. These are local results.
They must not be described as a successful GitHub Actions run until the pushed
commit's workflow has completed successfully.
