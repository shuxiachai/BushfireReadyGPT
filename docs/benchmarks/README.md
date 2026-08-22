# Benchmark Evidence

This folder contains machine-readable engineering regression results. It does
not contain stakeholder validation, production accuracy claims or emergency-use
evidence.

## Report Generation v0.4.0

`report-generation-v0.4.0.json` repeats the same eight declared product, safety
and degradation cases with the `v0.4.0` evaluator. The 2026-08-22 local run:

- passed every configured structural, evidence-binding, RAG-behaviour, topic,
  contamination, unsafe-live-claim and size gate;
- averaged `27.74 seconds` on the release machine;
- required one structural repair (`0.125` repair rate);
- measured average lexical evidence support `0.9540`;
- measured sentence-level citation coverage `0.2311` and cited-source precision
  `1.0000`;
- measured numeric consistency `0.9583` and zero jurisdiction conflicts;
- marked all eight reports `review_required` under the new grounding heuristic.

Grounding metrics in this release are deliberately diagnostic and are not part
of the aggregate `passed` decision. The JSON records
`grounding_release_gate_enforced: false`. Low citation coverage is a measured
report-authoring gap, not evidence that the reports are factually correct or
incorrect. Every claim still requires human checking against the current
official page before formal use.

Repeat the current run with:

```powershell
poetry run python scripts\evaluate_report_generation.py --output docs\benchmarks\report-generation-v0.4.0.json
```

## Report Generation v0.3.0

`report-generation-v0.3.0.json` records one real local-Ollama run against eight
declared cases:

- six product scenarios: school, council, community, household, aged care and farm;
- one live-route request that must remain outside the product safety boundary;
- one no-RAG case that must degrade explicitly rather than invent retrieval evidence.

The run used `bushfire-ready-qwen` with temperature `0.2`, seed `42` and a 2,300
token output limit. It passed all configured gates. The average latency of
`27.97 seconds` describes only the release machine and should not be compared
across hardware as a product performance claim.

The benchmark checks report structure, deterministic evidence binding, RAG
source-title attribution, expected RAG behavior, unsafe live claims, scenario
topic coverage, cross-scenario contamination, repair frequency and report size.
It does not establish that factual statements, legal wording or preparedness
actions are correct for a real organisation.

To repeat the run after Ollama, the report model and the verified RAG index are
available:

```powershell
poetry run python scripts\evaluate_report_generation.py --output docs\benchmarks\report-generation-v0.3.0.json
```

Hardware, model and corpus changes may legitimately change latency and model
wording. Review the complete JSON result and do not copy only the aggregate
`passed` field into external claims.
