"""Pure prospective SDK kwargs for one offline profile; never dispatch a model.

Rebuild the pinned rendering and its request on every accessor. Exact final
system/user messages and request-derived max_tokens are the only prompt/output
source. Metadata stays outside SDK kwargs. Model names are caller labels, not
proof that an alias resolves to the pinned model. Hashes establish consistency,
not capture, runtime equivalence, measurement truth or provider retention.

Reject-only project bounds (not provider acceptance limits): model name <=256
UTF-8 bytes, temperature an exact finite float in [0.0, 2.0], seed an exact int
in [0, 2**31-1], and positive max_tokens <=2**31-1. Complete final messages keep
their existing 256 KiB cap; kwargs add at most 8 KiB. No I/O, callbacks, SDK,
configuration, tokenization or transport occurs. PRIVATE kwargs must not be
logged or persisted. All effective budgets stay unknown and dispatch disabled.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_render as render
from scripts import section_local_repair_request as request

PROFILE_ID = "ollama-chat-completions-offline-v1"
SUMMARY_SCHEMA = "experimental-section-local-repair-invocation-summary-v1"
COMPARISON_SCHEMA = "experimental-section-local-repair-invocation-comparison-v1"
BUDGET_SCHEMA = "experimental-section-local-repair-invocation-budget-v1"
MAX_MODEL_NAME_BYTES = 256
MAX_KWARGS_BYTES = contract.MAX_MESSAGES_BYTES + 8192
_SUMMARY_LIMIT = 8192
_KWARGS_FIELDS = ("model", "messages", "temperature", "top_p", "max_tokens", "stream", "seed")
_INPUT_EXCEPTIONS = (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError)
REASON_CODES = frozenset(
    {
        "invocation_input_invalid",
        "invocation_limit_exceeded",
        "invocation_rendering_invalid",
        "invocation_output_tokens_invalid",
        "invocation_result_invalid",
        "invocation_not_a_prompt",
        "invocation_kwargs_invalid",
        "invocation_kwargs_mismatch",
        "invocation_budget_input_invalid",
        "invocation_rendered_prompt_binding_mismatch",
    }
)


class InvocationInputError(ValueError):
    """Fixed reason codes only, even if exception args/code are later mutated."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in REASON_CODES else "invocation_input_invalid"
        super().__init__(self.code)

    def __str__(self):
        return self.code if type(self.code) is str and self.code in REASON_CODES else "invocation_input_invalid"

    def __repr__(self):
        return f"InvocationInputError({str(self)!r})"


def _fail(code):
    raise InvocationInputError(code) from None


def _canonical_json(value, limit):
    try:
        return contract._canonical_json(value, limit)
    except contract.ContractInputError as error:
        _fail("invocation_limit_exceeded" if error.code == "input_limit_exceeded" else "invocation_input_invalid")


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _options(model_name, temperature, seed):
    try:
        contract._bounded_text(model_name, MAX_MODEL_NAME_BYTES)
    except contract.ContractInputError as error:
        _fail("invocation_limit_exceeded" if error.code == "input_limit_exceeded" else "invocation_input_invalid")
    if not model_name or model_name != model_name.strip() or not model_name.isprintable():
        _fail("invocation_input_invalid")
    if type(temperature) is not float or not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
        _fail("invocation_input_invalid")
    if type(seed) is not int or not 0 <= seed <= request.MAX_TOKEN_VALUE:
        _fail("invocation_input_invalid")


def _output_tokens(value):
    if type(value) is not int or not 1 <= value <= request.MAX_TOKEN_VALUE:
        _fail("invocation_output_tokens_invalid")
    return value


def _derive(rendered_request, model_name, temperature, seed):
    _options(model_name, temperature, seed)
    try:
        rendering, rendered_bytes = render._revalidate_rendering(rendered_request)
        data, _ = request._revalidate_request(rendered_request._prepared_request)
    except (render.RenderInputError, request.RequestInputError):
        _fail("invocation_rendering_invalid")
    kwargs = {
        "model": model_name,
        "messages": data["messages"],
        "temperature": temperature,
        "top_p": 0.8,
        "max_tokens": _output_tokens(data["budget_options"]["requested_output_tokens"]),
        "stream": True,
        "seed": seed,
    }
    kwargs_digest = _sha256(_canonical_json(kwargs, MAX_KWARGS_BYTES))
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "offline_invocation_prepared",
        "profile_id": PROFILE_ID,
        "render_profile_id": rendering["profile_id"],
        "rendering_sha256": rendered_request._binding_sha256,
        "request_sha256": rendering["request_sha256"],
        "messages_sha256": rendering["messages_sha256"],
        "rendered_prompt_sha256": rendering["rendered_prompt_sha256"],
        "rendered_prompt_bytes": rendering["rendered_prompt_bytes"],
        "kwargs_sha256": kwargs_digest,
        "model_name_sha256": _sha256(model_name),
        "model_name_resolution": "unverified_caller_label",
        "model_digest": rendering["model_digest"],
        "model_layer_sha256": rendering["model_layer_sha256"],
        "template_sha256": rendering["template_sha256"],
        "attempt_number": data["attempt_number"],
        "generation_kind": data["generation_kind"],
        "evidence_request_kind": data["evidence_request_kind"],
        "output_contract": data["output_contract"],
        "budget_options": data["budget_options"],
        "ollama_runtime_equivalence": "unknown",
        "effective_budget_status": "unknown",
        "eligible_for_model_dispatch": False,
        "production_acceptance": False,
    }
    return summary, kwargs, rendered_bytes


def _summary_digest(summary):
    return _sha256(_canonical_json(summary, _SUMMARY_LIMIT))


@dataclass(frozen=True)
class PreparedInvocation:
    """Immutable inputs; no saved kwargs or externally supplied derived summary."""

    _rendered_request: render.RenderedRequest = field(repr=False)
    _model_name: str = field(repr=False)
    _temperature: float = field(repr=False)
    _seed: int = field(repr=False)
    _binding_sha256: str = field(repr=False)

    def __str__(self):
        """Fail before generic prompt coercion can reach quota or transport."""
        _fail("invocation_not_a_prompt")

    def to_dict(self):
        """Return a detached, content-free summary after all bindings rebuild."""
        summary, _, _ = _revalidate_invocation(self)
        return {**summary, "invocation_sha256": self._binding_sha256}


def prepare_invocation(rendered_request, *, model_name: str, temperature: float, seed: int) -> PreparedInvocation:
    """Resolve prospective kwargs in memory, without authorizing their use."""
    try:
        summary, _, _ = _derive(rendered_request, model_name, temperature, seed)
        return PreparedInvocation(rendered_request, model_name, temperature, seed, _summary_digest(summary))
    except InvocationInputError:
        raise
    except _INPUT_EXCEPTIONS:
        _fail("invocation_input_invalid")


def _revalidate_invocation(invocation):
    try:
        if type(invocation) is not PreparedInvocation or not render._digest(invocation._binding_sha256):
            _fail("invocation_result_invalid")
        summary, kwargs, rendered_bytes = _derive(
            invocation._rendered_request, invocation._model_name, invocation._temperature, invocation._seed
        )
        if _summary_digest(summary) != invocation._binding_sha256:
            _fail("invocation_result_invalid")
        return summary, kwargs, rendered_bytes
    except _INPUT_EXCEPTIONS:
        _fail("invocation_result_invalid")


def completion_kwargs_for_offline_inspection(invocation):
    """Explicit PRIVATE INPUT accessor. Do not log, persist or transmit kwargs.

    Returns detached exact final messages and all profile options. This is a
    prospective call description, not a capture or a dispatch authorization.
    """
    _, kwargs, _ = _revalidate_invocation(invocation)
    return kwargs


def _validate_supplied_kwargs(value):
    # Bound builtin types before any equality, iteration or lookup hooks can run.
    encoded = _canonical_json(value, MAX_KWARGS_BYTES)
    # All validation and later comparison use this one detached snapshot.
    value = json.loads(encoded)
    if type(value) is not dict or set(value) != set(_KWARGS_FIELDS):
        _fail("invocation_kwargs_invalid")
    _options(value["model"], value["temperature"], value["seed"])
    _output_tokens(value["max_tokens"])
    if type(value["top_p"]) is not float or not 0.0 <= value["top_p"] <= 1.0 or type(value["stream"]) is not bool:
        _fail("invocation_kwargs_invalid")
    messages = value["messages"]
    _canonical_json(messages, contract.MAX_MESSAGES_BYTES)
    if type(messages) is not list or len(messages) != 2:
        _fail("invocation_kwargs_invalid")
    for message, role in zip(messages, ("system", "user"), strict=True):
        if (
            type(message) is not dict
            or set(message) != {"role", "content"}
            or message["role"] != role
            or type(message["content"]) is not str
            or not message["content"]
        ):
            _fail("invocation_kwargs_invalid")
    return encoded


def compare_invocation_kwargs(invocation, supplied_kwargs):
    """Compare supplied mock/observed data strictly; never claim SDK capture."""
    summary, expected, _ = _revalidate_invocation(invocation)
    try:
        supplied_json = _validate_supplied_kwargs(supplied_kwargs)
        supplied = json.loads(supplied_json)
        # Canonical serialization preserves builtin number types and exact text;
        # unlike Python == it cannot equate True with 1 or 1.0 with 1.
        mismatches = [
            name
            for name in _KWARGS_FIELDS
            if _canonical_json(supplied[name], MAX_KWARGS_BYTES) != _canonical_json(expected[name], MAX_KWARGS_BYTES)
        ]
        return {
            "schema": COMPARISON_SCHEMA,
            "status": "supplied_kwargs_mismatch" if mismatches else "supplied_kwargs_match",
            "reason_codes": ["invocation_kwargs_mismatch"] if mismatches else [],
            "invocation_sha256": invocation._binding_sha256,
            "expected_kwargs_sha256": summary["kwargs_sha256"],
            "supplied_kwargs_sha256": _sha256(supplied_json),
            "mismatched_fields": mismatches,
            "comparison_boundary": "supplied_data_only_not_authenticated_capture",
            "ollama_runtime_equivalence": "unknown",
            "effective_budget_status": "unknown",
            "eligible_for_model_dispatch": False,
            "production_acceptance": False,
        }
    except InvocationInputError:
        raise
    except _INPUT_EXCEPTIONS:
        _fail("invocation_kwargs_invalid")


def assess_invocation_budget(invocation, *, exact_count=None):
    """Bind supplied arithmetic to reconstructed bytes, with effective fit unknown.

    No counter runs. A supplied count remains untrusted even if its hashes and
    arithmetic agree; a missing count does not supply a rendered-prompt binding.
    """
    _, _, rendered_bytes = _revalidate_invocation(invocation)
    try:
        prepared = invocation._rendered_request._prepared_request
        if exact_count is None:
            budget = request.assess_request_budget(prepared)
        else:
            budget = request.assess_request_budget(prepared, exact_count=exact_count, rendered_prompt=rendered_bytes)
        return {**budget, "schema": BUDGET_SCHEMA, "invocation_sha256": invocation._binding_sha256}
    except request.RequestInputError as error:
        if error.code == "rendered_prompt_binding_mismatch":
            _fail("invocation_rendered_prompt_binding_mismatch")
        if error.code == "request_limit_exceeded":
            _fail("invocation_limit_exceeded")
        _fail("invocation_budget_input_invalid")
    except _INPUT_EXCEPTIONS:
        _fail("invocation_budget_input_invalid")
