"""Pure rendering for one explicit offline profile, never a runtime attestation.

The caller supplies the exact template bytes and pinned model identities. We
rebuild the PreparedRequest and evaluate only the nonempty system/user branch:
System = final system content; Messages = [final user]; no Tools, Prompt,
Response or default system. No I/O, tokenizer, transport or runtime is called.
This mapping does not prove what any Ollama runtime sent or whether input fits.
Hashes establish consistency only; they authenticate neither captures nor code.

Every result accessor revalidates the request, profile and derived rendering.
Summaries contain no input text. The separate PRIVATE byte accessor must not be
logged. Reject-only UTF-8 caps remain 256 KiB for final messages and 1 MiB for
the request and rendered prompt; the supplied template is capped at 8 KiB.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_request as request

SUMMARY_SCHEMA = "experimental-section-local-repair-render-summary-v1"
PROFILE_ID = "qwen2.5-7b-instruct-chatml-system-user-offline-v1"
MODEL_DIGEST = "21aa9b63ebd65652bfda214b8012ba0d61375855a448d7396ed57a7d7fa0f8ac"
MODEL_LAYER_SHA256 = "2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730"
TEMPLATE_SHA256 = "eb4402837c7829a690fa845de4d7f3fd842c2adee476d5341da8a46ea9255175"
CONTEXT_TOKENS = 8192
MAX_TEMPLATE_BYTES = 8192
MAX_RENDERED_BYTES = 1_048_576
_SUMMARY_LIMIT = 8192
_CONTROL_DELIMITERS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>")
# Verbatim 1482-byte snapshot from the locally installed Ollama qwen2.5:7b-derived
# model on 2026-10-11, bound by MODEL_DIGEST and TEMPLATE_SHA256 above.
# Versioned mapping reference: https://github.com/ollama/ollama/blob/v0.32.15/template/template.go
_TEMPLATE_BYTES = b"""{{- if .Messages }}
{{- if or .System .Tools }}<|im_start|>system
{{- if .System }}
{{ .System }}
{{- end }}
{{- if .Tools }}

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{- range .Tools }}
{"type": "function", "function": {{ .Function }}}
{{- end }}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>
{{- end }}<|im_end|>
{{ end }}
{{- range $i, $_ := .Messages }}
{{- $last := eq (len (slice $.Messages $i)) 1 -}}
{{- if eq .Role "user" }}<|im_start|>user
{{ .Content }}<|im_end|>
{{ else if eq .Role "assistant" }}<|im_start|>assistant
{{ if .Content }}{{ .Content }}
{{- else if .ToolCalls }}<tool_call>
{{ range .ToolCalls }}{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}
{{ end }}</tool_call>
{{- end }}{{ if not $last }}<|im_end|>
{{ end }}
{{- else if eq .Role "tool" }}<|im_start|>user
<tool_response>
{{ .Content }}
</tool_response><|im_end|>
{{ end }}
{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant
{{ end }}
{{- end }}
{{- else }}
{{- if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ end }}{{ .Response }}{{ if .Response }}<|im_end|>{{ end }}"""
REASON_CODES = frozenset(
    {
        "render_input_invalid",
        "render_limit_exceeded",
        "render_profile_unsupported",
        "render_profile_binding_mismatch",
        "render_template_mismatch",
        "render_messages_invalid",
        "render_control_delimiter_collision",
        "render_prepared_request_invalid",
        "render_result_invalid",
    }
)
_INPUT_EXCEPTIONS = (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError)


class RenderInputError(ValueError):
    """Only a fixed public reason code, never private text or nested exceptions."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in REASON_CODES else "render_input_invalid"
        super().__init__(self.code)


def _fail(code):
    raise RenderInputError(code) from None


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _canonical_json(value, limit):
    try:
        return contract._canonical_json(value, limit)
    except contract.ContractInputError as error:
        _fail("render_limit_exceeded" if error.code == "input_limit_exceeded" else "render_input_invalid")


def _validate_profile(profile_id, model_digest, model_layer_sha256, template_bytes, context_tokens):
    if type(profile_id) is not str or not _digest(model_digest) or not _digest(model_layer_sha256):
        _fail("render_input_invalid")
    if type(context_tokens) is not int or type(template_bytes) is not bytes:
        _fail("render_input_invalid")
    if len(profile_id) > 128 or len(template_bytes) > MAX_TEMPLATE_BYTES:
        _fail("render_limit_exceeded")
    if profile_id != PROFILE_ID:
        _fail("render_profile_unsupported")
    if (model_digest, model_layer_sha256, context_tokens) != (MODEL_DIGEST, MODEL_LAYER_SHA256, CONTEXT_TOKENS):
        _fail("render_profile_binding_mismatch")
    if template_bytes != _TEMPLATE_BYTES or _sha256(template_bytes) != TEMPLATE_SHA256:
        _fail("render_template_mismatch")


def _render_messages(messages):
    """Bound builtin data before inspecting it; preserve every content byte."""
    _canonical_json(messages, contract.MAX_MESSAGES_BYTES)
    if type(messages) is not list or len(messages) != 2:
        _fail("render_messages_invalid")
    for message, role in zip(messages, ("system", "user"), strict=True):
        if type(message) is not dict or set(message) != {"role", "content"}:
            _fail("render_messages_invalid")
        if message["role"] != role or type(message["content"]) is not str or not message["content"]:
            _fail("render_messages_invalid")
        if any(delimiter in message["content"] for delimiter in _CONTROL_DELIMITERS):
            _fail("render_control_delimiter_collision")
    rendered = (
        b"<|im_start|>system\n"
        + messages[0]["content"].encode("utf-8")
        + b"<|im_end|>\n<|im_start|>user\n"
        + messages[1]["content"].encode("utf-8")
        + b"<|im_end|>\n<|im_start|>assistant\n"
    )
    if len(rendered) > MAX_RENDERED_BYTES:
        _fail("render_limit_exceeded")
    return rendered


def _derive(prepared_request, profile_id, model_digest, model_layer_sha256, template_bytes, context_tokens):
    _validate_profile(profile_id, model_digest, model_layer_sha256, template_bytes, context_tokens)
    try:
        data, _ = request._revalidate_request(prepared_request)
    except request.RequestInputError:
        _fail("render_prepared_request_invalid")
    options = data["budget_options"]
    if (options["model_digest"], options["template_sha256"], options["context_tokens"]) != (
        MODEL_DIGEST,
        TEMPLATE_SHA256,
        CONTEXT_TOKENS,
    ):
        _fail("render_profile_binding_mismatch")
    rendered = _render_messages(data["messages"])
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "offline_profile_rendering_verified",
        "profile_id": PROFILE_ID,
        "request_sha256": prepared_request._binding_sha256,
        "messages_sha256": data["messages_sha256"],
        "model_digest": MODEL_DIGEST,
        "model_layer_sha256": MODEL_LAYER_SHA256,
        "template_sha256": TEMPLATE_SHA256,
        "context_tokens": CONTEXT_TOKENS,
        "rendered_prompt_sha256": _sha256(rendered),
        "rendered_prompt_bytes": len(rendered),
        "mapping": "system_to_System_user_to_Messages_no_tools_prompt_response_defaults",
        "ollama_runtime_equivalence": "unknown",
        "effective_budget_status": "unknown",
        "eligible_for_model_dispatch": False,
        "production_acceptance": False,
    }
    return summary, rendered


@dataclass(frozen=True)
class RenderedRequest:
    """Detached immutable inputs; only revalidated summaries are public output."""

    _prepared_request: request.PreparedRequest = field(repr=False)
    _profile_id: str = field(repr=False)
    _model_digest: str = field(repr=False)
    _model_layer_sha256: str = field(repr=False)
    _template_bytes: bytes = field(repr=False)
    _context_tokens: int = field(repr=False)
    _binding_sha256: str = field(repr=False)

    def to_dict(self):
        """Return a fresh, content-free summary after rebuilding every binding."""
        summary, _ = _revalidate_rendering(self)
        return summary


def _summary_digest(summary):
    return _sha256(_canonical_json(summary, _SUMMARY_LIMIT).encode("utf-8"))


def render_request_offline(
    prepared_request, *, profile_id, model_digest, model_layer_sha256, template_bytes, context_tokens
):
    """Render only the pinned explicit offline mapping; never assert runtime fit."""
    try:
        summary, _ = _derive(
            prepared_request, profile_id, model_digest, model_layer_sha256, template_bytes, context_tokens
        )
        return RenderedRequest(
            prepared_request,
            profile_id,
            model_digest,
            model_layer_sha256,
            template_bytes,
            context_tokens,
            _summary_digest(summary),
        )
    except RenderInputError:
        raise
    except _INPUT_EXCEPTIONS:
        _fail("render_input_invalid")


def _revalidate_rendering(rendered_request):
    try:
        if type(rendered_request) is not RenderedRequest or not _digest(rendered_request._binding_sha256):
            _fail("render_result_invalid")
        summary, rendered = _derive(
            rendered_request._prepared_request,
            rendered_request._profile_id,
            rendered_request._model_digest,
            rendered_request._model_layer_sha256,
            rendered_request._template_bytes,
            rendered_request._context_tokens,
        )
        if _summary_digest(summary) != rendered_request._binding_sha256:
            _fail("render_result_invalid")
        return summary, rendered
    except _INPUT_EXCEPTIONS:
        _fail("render_result_invalid")


def rendered_bytes_for_offline_count(rendered_request):
    """Explicit PRIVATE INPUT accessor; do not log or persist these bytes.

    Contains full private analysis, draft and evidence. Rebuilds the rendering;
    performs no counting and grants no permission to transmit or dispatch it.
    """
    _, rendered = _revalidate_rendering(rendered_request)
    return rendered
