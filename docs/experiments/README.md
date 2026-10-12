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

The [restricted renderer](../../scripts/section_local_repair_render.py) adds a
pinned two-message offline template profile. Reconstructing its exact bytes
does not authenticate native counting or the running Ollama service. A fresh
count-only measurement must remain separate from supplied-record diagnostics
and closed model campaigns; a measured excess is a valid result, not permission
to discard evidence or increase the configured model window.

The [offline invocation adapter](../../scripts/section_local_repair_invocation.py)
binds prospective completion kwargs to that rendered request, preserving the
full system/user pair and request-specific output reservation. It compares
supplied kwargs and delegates bound budget diagnostics without a client,
callback, environment lookup or model call. Its result is not a submission
capture, resolved model identity or permission to dispatch. It does not reopen
the closed count-only measurement or reuse its token count for a new request.

The separate `ControlledLocalModelExecutor` is a default-denied runtime harness,
not a model experiment entrypoint. Production has no admission issuer. Its
tests use isolated one-shot capabilities and fake SDK dependencies to exercise
exact submission, quota/deadline behavior and capture compatibility. Those
tests do not establish effective token fit or authorize a real model call.

The separate 2026-10-12 native count verified installed model files and measured
one fresh 27,785-byte synthetic invocation: 5,952 input + 2,300 output + 1 margin
= 8,253, exceeding the fixed 8,192-token offline budget by 61. It made no
generation call. Live Ollama identity/rendering remain unknown and dispatch is
still disabled; see the [bound measurement and limitations](../project_reassessment.md#installed-identity-and-fresh-native-budget-2026-10-12).

Use [current status](../project_reassessment.md) for maintained conclusions,
[RAG design](../rag.md) for runtime setup, and the
[script navigator](../../scripts/README.md) for tool roles.
