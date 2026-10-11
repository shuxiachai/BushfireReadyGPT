# Evidence-generation experiments

[The experiment record](evidence-generation.md) preserves the body-evidence
layout comparison, atomic/extractive selection, proposal contracts, two-stage
handoff and offline review clues. Failed runs, budget boundaries and semantic
unknowns remain alongside successful structural checks.

These are optional development tools, not the production report generator or
an independent report-accuracy benchmark. Historical raw outputs stay in their
existing locations; this folder does not create new model results or reopen
closed call journals.

The import-only [section-local repair contract](../../scripts/section_local_repair_contract.py)
checks supplied complete responses against a caller-declared edit scope and
their recorded evidence. It does not generate a patch, select failed sections,
construct prompts or run a model. An offline contract pass is not production
acceptance, token-budget admission or proof of provider receipt.

The separate [request helper](../../scripts/section_local_repair_request.py)
adds exact-span localisation, lossless input framing and final-message bindings.
Only fully accounted model-prose failures can produce a complete scope
recommendation, and the edit scope remains caller-declared. Global, owned or
unsupported failures stay unlocalised. Supplied count/hash consistency does not
prove model-template rendering: effective budget remains unknown and dispatch
is disabled. Both helpers are offline; neither reopens a recorded campaign.

Use [current status](../project_reassessment.md) for maintained conclusions,
[RAG design](../rag.md) for runtime setup, and the
[script navigator](../../scripts/README.md) for tool roles.
