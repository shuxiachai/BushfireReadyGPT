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

The real-model regression script now emits these metrics per scenario alongside
its existing structural, RAG-behaviour, attribution, safety and contamination
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
