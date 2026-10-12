"""Bounded Ollama 0.32.15 debug-render diagnostics, never a dispatch issuer.

Preparing a plan uses the installed OpenAI SDK against an in-memory transport.
The separate send function requires an explicit transport and spends its only
attempt before handing bytes to it. No daemon, files, configuration, environment
credentials or production capability are created here. A campaign must supply
the independently reviewed process ownership and lifecycle checks.

The debug route loads a runner and may allocate KV/warm up; it returns before
the Chat/Completion call, not necessarily before all model computation. Its
rendered text is before later BOS/add_special/truncation handling. Even matching
text plus a supplied token count cannot prove final KV use or issue admission.
All external observations are consistency evidence, not authenticated leases.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field

import httpx
import openai

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_invocation as invocation
from scripts import section_local_repair_render as render

VERSION = "0.32.15"
MODEL = "bushfire-ready-qwen:latest"
SYSTEM_SHA256 = "66b9ea09bd5b7099cbb4fc820f31b575c0366fa439b08245566692c6784e281e"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_WIRE_BYTES = invocation.MAX_KWARGS_BYTES
DEBUG_PATH = "/v1/chat/completions"
_NO_ADMISSION = {"eligible_for_model_dispatch": False, "production_acceptance": False}
_CODES = frozenset(
    {
        "input_invalid",
        "plan_invalid",
        "profile_mismatch",
        "response_invalid",
        "response_too_large",
        "response_status_rejected",
        "response_encoding_rejected",
        "wire_mismatch",
        "request_already_spent",
        "deadline_exceeded",
        "transport_failed",
        "metadata_invalid",
        "metadata_identity_mismatch",
        "metadata_changed",
        "debug_response_invalid",
        "count_binding_mismatch",
        "count_invalid",
        "sdk_debug_logging_enabled",
    }
)


class PreflightError(ValueError):
    """Fixed public codes; never nested transport errors or prompt contents."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in _CODES else "input_invalid"
        super().__init__(self.code)

    def __str__(self):
        return self.code if type(self.code) is str and self.code in _CODES else "input_invalid"


def require(condition, code):
    if not condition:
        raise PreflightError(code) from None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value, limit=MAX_RESPONSE_BYTES):
    try:
        return contract._canonical_json(value, limit).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise PreflightError("input_invalid") from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "response_invalid")
        result[key] = value
    return result


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_RESPONSE_BYTES, "response_too_large")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        canonical(result)
        require(type(result) is dict, "response_invalid")
        return result
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise PreflightError("response_invalid") from None


def _origin(value):
    require(type(value) is str and re.fullmatch(r"http://127\.0\.0\.1:[0-9]{4,5}", value), "input_invalid")
    port = int(value.rsplit(":", 1)[1])
    require(1024 <= port <= 65535 and port != 11434, "input_invalid")
    return value


def _projection(prepared):
    try:
        summary, kwargs, rendered = invocation._revalidate_invocation(prepared)
        require(kwargs["model"] == MODEL and kwargs["max_tokens"] == 2300, "profile_mismatch")
        require(summary["budget_options"]["context_tokens"] == 8192, "profile_mismatch")
        require(summary["budget_options"]["margin_tokens"] == 1, "profile_mismatch")
        projected = {**kwargs, "stream": False, "_debug_render_only": True}
        return summary, kwargs, projected, rendered
    except invocation.InvocationInputError:
        raise PreflightError("plan_invalid") from None


class _DiagnosticSDK(openai.OpenAI):
    def platform_headers(self):
        # These optional SDK telemetry headers probe platform.platform(), which
        # can launch `ver` on Windows. Omit them in both mock and actual calls;
        # leave all SDK request serialization, HTTP and response parsing intact.
        return {}


def _sdk_call(prepared, origin, transport, timeout):
    # SDK DEBUG logging includes json_data, which contains the complete prompt.
    # Inspect effective levels before constructing options; do not mutate global
    # logging configuration or rely on OPENAI_LOG being absent in the caller.
    names = {"openai", "openai._base_client", "openai._response"}
    names.update(name for name in logging.Logger.manager.loggerDict if name.startswith("openai."))
    require(not any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in names), "sdk_debug_logging_enabled")
    _, kwargs, _, _ = _projection(prepared)
    # Explicit dummy string: no environment key, .env, SDK retry or redirect.
    with httpx.Client(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        headers={"Accept-Encoding": "identity"},
    ) as client:
        sdk = _DiagnosticSDK(
            api_key="ollama-local-diagnostic-no-secret",
            organization="",
            project="",
            base_url=origin + "/v1",
            http_client=client,
            max_retries=0,
            timeout=timeout,
        )
        try:
            sdk.chat.completions.create(**{**kwargs, "stream": False}, extra_body={"_debug_render_only": True})
        except Exception:
            # OpenAI wraps transport failures with possibly sensitive request data.
            raise PreflightError("transport_failed") from None


@dataclass(frozen=True)
class DebugPlan:
    _prepared: invocation.PreparedInvocation = field(repr=False)
    _origin: str = field(repr=False)
    _run_id: str = field(repr=False)
    _wire: bytes = field(repr=False)
    _sdk_version: str = field(repr=False)
    _binding: str = field(repr=False)

    def to_dict(self):
        return _plan_summary(self)


def _plan_summary(plan):
    require(type(plan) is DebugPlan and type(plan._wire) is bytes and len(plan._wire) <= MAX_WIRE_BYTES, "plan_invalid")
    require(type(plan._run_id) is str and re.fullmatch(r"[a-f0-9]{32}", plan._run_id), "plan_invalid")
    require(plan._sdk_version == openai.__version__, "plan_invalid")
    summary, _, projected, rendered = _projection(plan._prepared)
    require(canonical(decode(plan._wire)) == canonical(projected), "wire_mismatch")
    result = {
        "schema": "ollama-debug-plan-v1",
        "run_id": plan._run_id,
        "origin": _origin(plan._origin),
        "method": "POST",
        "path": DEBUG_PATH,
        "ollama_version": VERSION,
        "sdk_version": plan._sdk_version,
        "invocation_sha256": plan._prepared._binding_sha256,
        "original_kwargs_sha256": summary["kwargs_sha256"],
        "debug_projection_sha256": sha(canonical(projected)),
        "wire_body_sha256": sha(plan._wire),
        "wire_body_bytes": len(plan._wire),
        "offline_rendered_sha256": sha(rendered),
        "offline_rendered_bytes": len(rendered),
        "output_tokens": 2300,
        "context_tokens": 8192,
        "margin_tokens": 1,
        "projection_changes": ["stream_true_to_false", "_debug_render_only_true"],
        "effective_budget_status": "unknown",
        **_NO_ADMISSION,
    }
    require(plan._binding == sha(canonical(result)), "plan_invalid")
    return {**result, "plan_sha256": plan._binding}


def prepare_debug_plan(prepared, *, origin, run_id):
    """Observe exact SDK serialization in memory; this makes no socket calls."""
    _origin(origin)
    require(type(run_id) is str and re.fullmatch(r"[a-f0-9]{32}", run_id), "input_invalid")
    summary, _, projected, rendered = _projection(prepared)
    captured = []

    def capture(request):
        require(not captured and request.method == "POST" and str(request.url) == origin + DEBUG_PATH, "wire_mismatch")
        raw = request.read()
        require(len(raw) <= MAX_WIRE_BYTES and canonical(decode(raw)) == canonical(projected), "wire_mismatch")
        captured.append(raw)
        return httpx.Response(
            200,
            json={
                "id": "offline-serialization-only",
                "object": "chat.completion",
                "created": 0,
                "model": MODEL,
                "choices": [],
            },
        )

    _sdk_call(prepared, origin, httpx.MockTransport(capture), 1.0)
    require(len(captured) == 1, "wire_mismatch")
    result = {
        "schema": "ollama-debug-plan-v1",
        "run_id": run_id,
        "origin": origin,
        "method": "POST",
        "path": DEBUG_PATH,
        "ollama_version": VERSION,
        "sdk_version": openai.__version__,
        "invocation_sha256": prepared._binding_sha256,
        "original_kwargs_sha256": summary["kwargs_sha256"],
        "debug_projection_sha256": sha(canonical(projected)),
        "wire_body_sha256": sha(captured[0]),
        "wire_body_bytes": len(captured[0]),
        "offline_rendered_sha256": sha(rendered),
        "offline_rendered_bytes": len(rendered),
        "output_tokens": 2300,
        "context_tokens": 8192,
        "margin_tokens": 1,
        "projection_changes": ["stream_true_to_false", "_debug_render_only_true"],
        "effective_budget_status": "unknown",
        **_NO_ADMISSION,
    }
    return DebugPlan(prepared, origin, run_id, captured[0], openai.__version__, sha(canonical(result)))


class FixedRequestTransport(httpx.BaseTransport):
    """One method/URL/body and one bounded response. A failure also spends it.

    ``inner`` is explicit so tests cannot accidentally open sockets. The campaign
    owns constructing HTTPTransport(trust_env=False, retries=0) after review.
    This is an in-process guard, not an access control boundary for the daemon.
    """

    def __init__(self, *, method, url, body, inner, deadline):
        require(method in ("GET", "POST") and type(url) is str and type(body) is bytes, "input_invalid")
        parsed = httpx.URL(url)
        _origin(f"{parsed.scheme}://{parsed.host}:{parsed.port}")
        require(not parsed.query and not parsed.userinfo and not parsed.fragment, "input_invalid")
        allowed = {
            "GET": {"/api/version", "/api/tags", "/api/ps", "/api/status"},
            "POST": {DEBUG_PATH, "/api/show", "/tokenize", "/detokenize"},
        }
        require(parsed.path in allowed[method], "input_invalid")
        require(type(deadline) in (float, int) and math.isfinite(deadline), "input_invalid")
        require(len(body) <= MAX_RESPONSE_BYTES, "input_invalid")
        self.method, self.url, self.body = method, url, body
        self.inner, self.deadline = inner, deadline
        self.attempts = 0
        self.response_body = None
        self.error_code = None
        self._lock = threading.Lock()

    def handle_request(self, request):
        with self._lock:
            require(self.attempts == 0, "request_already_spent")
            self.attempts = 1
        try:
            require(time.monotonic() < self.deadline, "deadline_exceeded")
            require(
                request.method == self.method and str(request.url) == self.url and request.read() == self.body,
                "wire_mismatch",
            )
            require(request.headers.get("accept-encoding") == "identity", "wire_mismatch")
            if self.method == "POST":
                require(request.headers.get("content-type") == "application/json", "wire_mismatch")
            require("transfer-encoding" not in request.headers, "wire_mismatch")
            if self.body:
                require(request.headers.get("content-length") == str(len(self.body)), "wire_mismatch")
            # HTTPX timeouts are per-operation; the campaign adds a wall watchdog.
            remaining = max(0.001, self.deadline - time.monotonic())
            request.extensions["timeout"] = {
                name: min(remaining, 60.0) for name in ("connect", "read", "write", "pool")
            }
            response = self.inner.handle_request(request)
            try:
                require(response.status_code == 200, "response_status_rejected")
                require(
                    response.headers.get("content-encoding", "identity") == "identity", "response_encoding_rejected"
                )
                require(
                    response.headers.get("content-type", "").split(";", 1)[0] == "application/json", "response_invalid"
                )
                length = response.headers.get("content-length")
                require(
                    length is None or (length.isdecimal() and int(length) <= MAX_RESPONSE_BYTES), "response_too_large"
                )
                chunks, total = [], 0
                for chunk in response.iter_raw():
                    require(time.monotonic() < self.deadline, "deadline_exceeded")
                    total += len(chunk)
                    require(total <= MAX_RESPONSE_BYTES, "response_too_large")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                decode(raw)
                self.response_body = raw
                return httpx.Response(200, headers={"content-type": "application/json"}, content=raw)
            finally:
                response.close()
        except PreflightError as error:
            self.error_code = str(error)
            raise
        except Exception:
            self.error_code = "transport_failed"
            raise PreflightError("transport_failed") from None

    def close(self):
        self.inner.close()


def send_debug_once(plan, *, transport):
    """Run the installed SDK through the preconstructed, exact single-use guard."""
    _plan_summary(plan)
    require(
        type(transport) is FixedRequestTransport
        and transport.method == "POST"
        and transport.url == plan._origin + DEBUG_PATH
        and transport.body == plan._wire,
        "wire_mismatch",
    )
    try:
        _sdk_call(plan._prepared, plan._origin, transport, 60.0)
    except PreflightError as error:
        raise PreflightError(transport.error_code or str(error)) from None
    require(transport.attempts == 1 and type(transport.response_body) is bytes, "transport_failed")
    return transport.response_body


def metadata_snapshot(plan, *, version, tags, show, owner):
    """Check raw local observations. Caller owns OS/PID inspection, not this data.

    API v0.32.15 uses omitempty for remote/system/messages. Empty omissions are
    normalized only for those documented optional fields; identity and template
    fields are required. The pinned manifest has a nonempty default system.
    Its hash is checked even though explicit final messages override it.
    """
    _plan_summary(plan)
    data = json.loads(canonical({"version": version, "tags": tags, "show": show, "owner": owner}))
    version, tags, show, owner = (data[key] for key in ("version", "tags", "show", "owner"))
    require(all(type(item) is dict for item in (version, tags, show, owner)), "metadata_invalid")
    require(version.get("version") == VERSION, "metadata_identity_mismatch")
    require(type(tags.get("models")) is list, "metadata_invalid")
    matches = [row for row in tags["models"] if type(row) is dict and row.get("name") == MODEL]
    require(len(matches) == 1, "metadata_identity_mismatch")
    model = matches[0]
    require(model.get("model") == MODEL and model.get("digest") == render.MODEL_DIGEST, "metadata_identity_mismatch")
    require(
        all(item.get(key, "") == "" for item in (show, model) for key in ("remote_host", "remote_model")),
        "metadata_identity_mismatch",
    )
    require(type(show.get("template")) is str and 0 < len(show["template"].encode()) <= 65536, "metadata_invalid")
    require(
        type(show.get("system")) is str and sha(show["system"].encode()) == SYSTEM_SHA256, "metadata_identity_mismatch"
    )
    require(
        show.get("messages", []) == [] and show.get("renderer", "") == "" and show.get("parser", "") == "",
        "metadata_identity_mismatch",
    )
    require(type(show.get("parameters")) is str, "metadata_invalid")
    parameters = {}
    for line in show["parameters"].splitlines():
        pair = line.split()
        require(len(pair) == 2 and pair[0] not in parameters, "metadata_invalid")
        parameters[pair[0]] = pair[1]
    require(parameters == {"num_ctx": "8192", "temperature": "0.7"}, "metadata_identity_mismatch")
    require(type(show.get("modelfile")) is str, "metadata_invalid")
    from_lines = [line[5:].strip().strip('"') for line in show["modelfile"].splitlines() if line.startswith("FROM ")]
    require(
        len(from_lines) == 1
        and from_lines[0].replace("\\", "/").rsplit("/", 1)[-1] == "sha256-" + render.MODEL_LAYER_SHA256,
        "metadata_identity_mismatch",
    )
    require(
        not any(
            line.startswith(("ADAPTER ", "DRAFT ", "MESSAGE ", "RENDERER ", "PARSER "))
            for line in show["modelfile"].splitlines()
        ),
        "metadata_identity_mismatch",
    )
    require(
        type(show.get("model_info")) is dict and show["model_info"].get("general.architecture") == "qwen2",
        "metadata_identity_mismatch",
    )
    _validate_owner(plan, owner)
    selected_sha = sha(show["template"].encode())
    result = {
        "schema": "ollama-metadata-observation-v1",
        "run_id": plan._run_id,
        "plan_sha256": plan._binding,
        "version": VERSION,
        "alias": MODEL,
        "model_digest": render.MODEL_DIGEST,
        "model_layer_sha256": render.MODEL_LAYER_SHA256,
        "manifest_template_sha256": render.TEMPLATE_SHA256,
        "server_selected_template_sha256": selected_sha,
        "selected_template_matches_manifest": selected_sha == render.TEMPLATE_SHA256,
        "system_sha256": SYSTEM_SHA256,
        "model_parameters": parameters,
        "model_messages": [],
        "remote_host": "",
        "remote_model": "",
        "owner": owner,
        "boundary": "unauthenticated_loopback_observation_no_identity_lease",
        **_NO_ADMISSION,
    }
    snapshot = {**result, "snapshot_sha256": sha(canonical(result))}
    _validate_snapshot(plan, snapshot)
    return snapshot


def _validate_owner(plan, owner):
    require(
        type(owner) is dict and set(owner) == {"pid", "created_utc", "executable_sha256", "listener", "in_owned_job"},
        "metadata_invalid",
    )
    require(
        type(owner["pid"]) is int
        and 0 < owner["pid"] <= 2**32 - 1
        and owner["in_owned_job"] is True
        and type(owner["created_utc"]) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?(?:Z|\+00:00)", owner["created_utc"]
        )
        and render._digest(owner["executable_sha256"])
        and owner["listener"] == plan._origin,
        "metadata_identity_mismatch",
    )


def _validate_snapshot(plan, snapshot):
    canonical(snapshot)
    fixed = {
        "schema": "ollama-metadata-observation-v1",
        "run_id": plan._run_id,
        "plan_sha256": plan._binding,
        "version": VERSION,
        "alias": MODEL,
        "model_digest": render.MODEL_DIGEST,
        "model_layer_sha256": render.MODEL_LAYER_SHA256,
        "manifest_template_sha256": render.TEMPLATE_SHA256,
        "system_sha256": SYSTEM_SHA256,
        "model_parameters": {"num_ctx": "8192", "temperature": "0.7"},
        "model_messages": [],
        "remote_host": "",
        "remote_model": "",
        "boundary": "unauthenticated_loopback_observation_no_identity_lease",
        **_NO_ADMISSION,
    }
    require(
        type(snapshot) is dict
        and set(snapshot)
        == set(fixed)
        | {"server_selected_template_sha256", "selected_template_matches_manifest", "owner", "snapshot_sha256"},
        "metadata_invalid",
    )
    require(
        all(canonical(snapshot[key]) == canonical(value) for key, value in fixed.items()), "metadata_identity_mismatch"
    )
    selected = snapshot["server_selected_template_sha256"]
    require(
        render._digest(selected)
        and snapshot["selected_template_matches_manifest"] is (selected == render.TEMPLATE_SHA256),
        "metadata_invalid",
    )
    _validate_owner(plan, snapshot["owner"])
    payload = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    require(
        render._digest(snapshot["snapshot_sha256"]) and snapshot["snapshot_sha256"] == sha(canonical(payload)),
        "metadata_invalid",
    )


def assess_diagnostic(plan, *, before, after, raw_response, supplied_count=None):
    """Compare text and request-bound arithmetic; production admission stays shut."""
    _plan_summary(plan)
    for snapshot in (before, after):
        _validate_snapshot(plan, snapshot)
    require(canonical(before) == canonical(after), "metadata_changed")
    response = decode(raw_response)
    require(response.get("model") == MODEL and response.get("object") == "chat.completion", "debug_response_invalid")
    require(response.get("remote_host", "") == "" and response.get("remote_model", "") == "", "debug_response_invalid")
    debug = response.get("_debug_info")
    require(
        type(debug) is dict and set(debug) in ({"rendered_template"}, {"rendered_template", "image_count"}),
        "debug_response_invalid",
    )
    # api.DebugInfo.image_count uses omitempty at zero in this exact version.
    require(
        type(debug.get("image_count", 0)) is int
        and debug.get("image_count", 0) == 0
        and type(debug["rendered_template"]) is str,
        "debug_response_invalid",
    )
    actual = debug["rendered_template"].encode("utf-8")
    require(0 < len(actual) <= render.MAX_RENDERED_BYTES, "debug_response_invalid")
    choices = response.get("choices")
    require(type(choices) is list and len(choices) == 1 and type(choices[0]) is dict, "debug_response_invalid")
    choice = choices[0]
    message = choice.get("message")
    require(
        choice.get("index") == 0 and "finish_reason" in choice and choice["finish_reason"] is None,
        "debug_response_invalid",
    )
    # Both 0.32.15 debug branches omit api.ChatResponse.Message. The nonstream
    # compatibility converter preserves its zero-value role (empty string).
    require(
        type(message) is dict
        and message.get("role") == ""
        and message.get("content") == ""
        and all(value in (None, [], "") for key, value in message.items() if key not in {"role", "content"}),
        "debug_response_invalid",
    )
    usage = response.get("usage")
    require(
        type(usage) is dict
        and set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens"}
        and all(type(value) is int and value == 0 for value in usage.values()),
        "debug_response_invalid",
    )
    _, _, _, expected = _projection(plan._prepared)
    same = actual == expected
    arithmetic = {"status": "unknown", "input_tokens": None, "reason": "same_runner_count_unavailable"}
    if supplied_count is not None:
        canonical(supplied_count)
        fields = {
            "plan_sha256",
            "run_id",
            "rendered_sha256",
            "model_digest",
            "input_tokens",
            "context_tokens",
            "output_tokens",
            "margin_tokens",
            "runner_identity_sha256",
            "count_method",
        }
        require(type(supplied_count) is dict and set(supplied_count) == fields, "count_invalid")
        required = {
            "plan_sha256": plan._binding,
            "run_id": plan._run_id,
            "rendered_sha256": sha(actual),
            "model_digest": render.MODEL_DIGEST,
            "context_tokens": 8192,
            "output_tokens": 2300,
            "margin_tokens": 1,
            "count_method": "same_owned_runner_tokenize_detokenize",
        }
        require(
            all(canonical(supplied_count[key]) == canonical(value) for key, value in required.items()),
            "count_binding_mismatch",
        )
        n = supplied_count["input_tokens"]
        require(
            type(n) is int and 0 < n <= 262144 and render._digest(supplied_count["runner_identity_sha256"]),
            "count_invalid",
        )
        total = n + 2300 + 1
        arithmetic = {
            "status": "fits" if total <= 8192 else "exceeds",
            "input_tokens": n,
            "total_tokens": total,
            "remaining_tokens": 8192 - total,
            "provenance": "supplied_observation_not_authenticated_by_this_helper",
        }
    return {
        "schema": "ollama-debug-assessment-v1",
        "run_id": plan._run_id,
        "plan_sha256": plan._binding,
        "invocation_sha256": plan._prepared._binding_sha256,
        "wire_body_sha256": sha(plan._wire),
        "response_body_sha256": sha(raw_response),
        "response_rendered_sha256": sha(actual),
        "response_rendered_bytes": len(actual),
        "offline_rendered_sha256": sha(expected),
        "rendered_bytes_match": same,
        "status": "debug_render_matches" if same else "debug_render_mismatch",
        "metadata_snapshot_sha256": before["snapshot_sha256"],
        "server_selected_template_sha256": before["server_selected_template_sha256"],
        "selected_template_matches_manifest": before["selected_template_matches_manifest"],
        "arithmetic": arithmetic,
        "effective_budget_status": "unknown",
        "admission_status": "rejected",
        "generation_success": False,
        "zero_usage_is_not_input_measurement": True,
        "final_kv_sequence_verified": False,
        "reason": "render_mismatch"
        if not same
        else "budget_exceeds"
        if arithmetic["status"] == "exceeds"
        else "final_kv_and_production_admission_unproven",
        **_NO_ADMISSION,
    }
