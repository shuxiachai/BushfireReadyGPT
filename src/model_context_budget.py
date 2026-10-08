"""Offline assessment of a supplied, exact prompt token measurement.

This module is deliberately diagnostic: it neither renders prompts nor calls a
model/tokenizer.  A ``fits`` result is possible only when a caller supplies a
complete, bound exact measurement from an allowlisted offline method.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.model_evidence import json_sha256, text_sha256

ASSESSMENT_SCHEMA = "model-context-budget-assessment-v1"
VERIFICATION_BOUNDARY = (
    "checks supplied exact-count provenance bindings; does not authenticate measurement/provider retention"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXACT_METHODS = {"llama_cpp_tokenize", "verified_offline_tokenizer"}
_EXACT_FIELDS = {
    "scope",
    "model_digest",
    "template_sha256",
    "messages_sha256",
    "context_tokens",
    "rendered_prompt_sha256",
    "tokenizer_identity",
    "input_tokens",
    "count_method",
}
_HASH_FIELDS = ("model_digest", "template_sha256", "messages_sha256", "rendered_prompt_sha256")


def _nonnegative_int(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return value


def _optional_hash(value, name):
    if value is not None and (type(value) is not str or not _SHA256.fullmatch(value)):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest or None.")
    return value


def _required_hash(value, name):
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest.")
    return value


def _bounded_identity(value, name, limit):
    if type(value) is not str or not value.strip() or len(value) > limit or not value.isprintable():
        raise ValueError(f"{name} must be a nonblank bounded printable string.")
    return value


def _validate_exact_count(value):
    if type(value) is not dict:
        raise ValueError("exact_count must be an object or None.")
    if set(value) - _EXACT_FIELDS:
        raise ValueError("exact_count contains unsupported fields.")
    # Missing fields leave the measurement unknown; malformed supplied fields
    # are invalid even when other required fields are absent.
    for key in _HASH_FIELDS:
        if key in value:
            _required_hash(value[key], f"exact_count.{key}")
    for key in ("context_tokens", "input_tokens"):
        if key in value:
            _nonnegative_int(value[key], f"exact_count.{key}")
    for key, limit in (("scope", 128), ("count_method", 128), ("tokenizer_identity", 256)):
        if key in value:
            _bounded_identity(value[key], f"exact_count.{key}", limit)


def _messages(value):
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("messages must be a sequence of role/content objects.")
    for item in value:
        if type(item) is not dict or set(item) != {"role", "content"}:
            raise ValueError("Each message must contain exactly role and content.")
        if type(item["role"]) is not str or type(item["content"]) is not str:
            raise ValueError("Message role and content must be strings.")
    return value


def _result(
    *,
    status,
    reason,
    input_tokens,
    requested_output_tokens,
    context_tokens,
    margin_tokens,
    model_digest,
    template_sha256,
    messages_sha256,
    rendered_prompt_sha256=None,
    tokenizer_identity_sha256=None,
    count_method=None,
):
    reserved_total = headroom = None
    if input_tokens is not None and context_tokens is not None:
        reserved_total = input_tokens + requested_output_tokens + margin_tokens
        headroom = context_tokens - reserved_total
    return {
        "schema": ASSESSMENT_SCHEMA,
        "status": status,
        "reason": reason,
        "input_tokens": input_tokens,
        "output_tokens": requested_output_tokens,
        "context_tokens": context_tokens,
        "margin_tokens": margin_tokens,
        "reserved_total": reserved_total,
        "headroom": headroom,
        "model_digest": model_digest,
        "template_sha256": template_sha256,
        "messages_sha256": messages_sha256,
        "rendered_prompt_sha256": rendered_prompt_sha256,
        "tokenizer_identity_sha256": tokenizer_identity_sha256,
        "count_method": count_method,
        "verification_boundary": VERIFICATION_BOUNDARY,
    }


def assess_model_context_budget(
    *,
    messages,
    model_digest=None,
    template_sha256=None,
    context_tokens=None,
    requested_output_tokens,
    margin_tokens=1,
    exact_count=None,
):
    """Check supplied bindings, not the truth of a caller's token measurement.

    Free-text metadata is hashed or omitted from the diagnostic, as it may
    contain prompt content. Messages are hashed exactly without normalization.
    """
    messages = _messages(messages)
    model_digest = _optional_hash(model_digest, "model_digest")
    template_sha256 = _optional_hash(template_sha256, "template_sha256")
    if context_tokens is not None:
        _nonnegative_int(context_tokens, "context_tokens")
    _nonnegative_int(requested_output_tokens, "requested_output_tokens")
    _nonnegative_int(margin_tokens, "margin_tokens")
    messages_sha256 = json_sha256(messages)
    result_fields = {
        "requested_output_tokens": requested_output_tokens,
        "context_tokens": context_tokens,
        "margin_tokens": margin_tokens,
        "model_digest": model_digest,
        "template_sha256": template_sha256,
        "messages_sha256": messages_sha256,
    }

    if exact_count is None:
        return _result(
            status="unknown",
            reason="missing_exact_count_binding",
            input_tokens=None,
            **result_fields,
        )
    _validate_exact_count(exact_count)
    count_method = exact_count.get("count_method")
    result_fields.update(
        count_method=count_method if count_method in _EXACT_METHODS else None,
        rendered_prompt_sha256=exact_count.get("rendered_prompt_sha256"),
        tokenizer_identity_sha256=(
            text_sha256(exact_count["tokenizer_identity"]) if "tokenizer_identity" in exact_count else None
        ),
    )
    missing = _EXACT_FIELDS - set(exact_count)
    if missing:
        return _result(
            status="unknown",
            reason="missing_exact_count_binding",
            input_tokens=None,
            **result_fields,
        )

    bindings = {
        "model_digest": model_digest,
        "template_sha256": template_sha256,
        "messages_sha256": messages_sha256,
        "context_tokens": context_tokens,
    }
    if exact_count["scope"] != "full_rendered_prompt":
        return _result(status="unknown", reason="unsupported_exact_count_scope", input_tokens=None, **result_fields)
    if model_digest is None or template_sha256 is None or context_tokens is None:
        return _result(status="unknown", reason="missing_context_binding", input_tokens=None, **result_fields)
    if any(exact_count[key] != value for key, value in bindings.items()):
        return _result(status="unknown", reason="exact_count_binding_mismatch", input_tokens=None, **result_fields)
    if count_method not in _EXACT_METHODS:
        return _result(status="unknown", reason="unsupported_count_method", input_tokens=None, **result_fields)

    input_tokens = exact_count["input_tokens"]
    reserved_total = input_tokens + requested_output_tokens + margin_tokens
    return _result(
        status="fits" if reserved_total <= context_tokens else "exceeds",
        reason="exact_count_bound",
        input_tokens=input_tokens,
        **result_fields,
    )
