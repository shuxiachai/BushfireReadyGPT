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

Subsequent fixed-guidance deduplication removes 237 UTF-8 bytes without changing
the framed input data. A separate single count on `bde7ee7` measured the same
case at 5,899 input tokens, **53 fewer**, but 5,899 + 2,300 + 1 = 8,200 still
exceeds the window by **8**. No generation or production admission occurred.
See the [same-case measurement and boundaries](../project_reassessment.md#native-count-after-guidance-reduction-2026-10-12);
byte savings alone were not used as token evidence.

Removing only the redundant 64-byte task introduction was then measured once
on `b2646f5`: the same case uses **5,888 input tokens**, and 5,888 + 2,300 + 1
= 8,189 leaves only **3 tokens** in the fixed offline window. This is not a
general capacity or live Ollama fit claim; no generation/admission occurred.
See the [single-case result and limitations](../project_reassessment.md#single-case-offline-fit-after-intro-removal-2026-10-12).

The separate [Ollama diagnostic](../../scripts/ollama_preflight.py) binds a
version-specific debug-render request and always denies production admission.
Its two isolated startup checks on `65aa791` both stopped before any campaign
HTTP request. The follow-up recorded a path matching Windows `conhost.exe`,
but not its trusted binary/argument identity. No live render or new count was
obtained; the 5,888-token offline result remains separate. Both failed attempts
are closed, with owned model copies/keys removed and historical evidence kept.
See the [startup outcomes and remaining boundary](../project_reassessment.md#online-diagnostic-implemented-windows-startup-boundary-unresolved-2026-10-12).

Use [current status](../project_reassessment.md) for maintained conclusions,
[RAG design](../rag.md) for runtime setup, and the
[script navigator](../../scripts/README.md) for tool roles.
