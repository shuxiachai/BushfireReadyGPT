"""Stateless, tool-free model access for governed report generation."""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from src.config import (
    IS_LOCAL_LLM,
    LLM_PROVIDER,
    MODEL_MAX_TOKENS,
    MODEL_SEED,
    MODEL_TEMPERATURE,
    MODEL_TIMEOUT_SECONDS,
    client,
    is_loopback_model_endpoint,
    model,
    validate_model_endpoint,
)
from src.current_model_evidence import OUTPUT_CONTRACTS, SECTION_PROSE_OUTPUT_CONTRACT
from src.deployment_access import DeploymentConfigurationError
from src.model_evidence import (
    CapturedMessages,
    bind_submitted_messages,
    text_sha256,
)
from src.model_limits import ModelAllowanceError, acquire_model_slot
from src.model_response import ModelResponseError, ModelServiceError, record_response_admission
from src.section_protocol_error import SectionProtocolError

GOVERNED_MODEL_SYSTEM_PROMPT = """You are the governed report-generation engine for BushfireReadyGPT.
Process only the current request. Do not retain conversational history, call tools, emit tool-call syntax, or
claim that you accessed live emergency information. Return only the requested English Markdown report. Follow
the safety, evidence, structure and human-review requirements in the current request exactly."""
LOGGER = logging.getLogger(__name__)
SECTION_PROSE_SYSTEM_PROMPT = """You are the governed report-generation engine for BushfireReadyGPT.
Process only the current request. Do not retain history, call tools or claim live emergency access.
Return only one strict JSON object containing exactly s01 through s15, each a nonempty English prose string.
The application supplies headings, frozen fields, source register and appendices. Follow the request's safety,
evidence and human-review requirements. No Markdown headings, fences, preface or extra JSON fields."""


def build_governed_messages(prompt):
    """Construct the same mode-specific messages for transport and diagnostics."""
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise ValueError("A governed model prompt is required.")
    contract = getattr(prompt, "output_contract", "markdown")
    if not isinstance(contract, str) or contract not in OUTPUT_CONTRACTS:
        raise ValueError("Unsupported model output contract.")
    system = SECTION_PROSE_SYSTEM_PROMPT if contract == SECTION_PROSE_OUTPUT_CONTRACT else GOVERNED_MODEL_SYSTEM_PROMPT
    return CapturedMessages(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_text},
        ]
    )


def _single_choice(response):
    choices = getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        raise ModelResponseError("invalid")
    choice = choices[0]
    index = getattr(choice, "index", 0)
    if type(index) is not int or index != 0:
        raise ModelResponseError("invalid")
    return choice


def _require_normal_stop(reason):
    if reason != "stop":
        raise ModelResponseError("missing" if reason is None else reason)


def _text_only_payload(payload):
    if getattr(payload, "tool_calls", None):
        raise ModelResponseError("tool_calls")
    if getattr(payload, "function_call", None):
        raise ModelResponseError("function_call")
    if getattr(payload, "refusal", None):
        raise ModelResponseError("content_filter")
    content = getattr(payload, "content", None)
    if content is not None and not isinstance(content, str):
        raise ModelResponseError("invalid")
    return content or ""


class _StreamResponse:
    def __init__(self):
        self.parts = []
        self.finished = False

    def add(self, chunk):
        if getattr(chunk, "choices", None) == []:
            return  # Usage-only trailers do not contain completion choices.
        choice = _single_choice(chunk)
        if self.finished:
            raise ModelResponseError("invalid")
        content = _text_only_payload(getattr(choice, "delta", None))
        reason = getattr(choice, "finish_reason", None)
        if reason is not None:
            _require_normal_stop(reason)
            self.finished = True
        if content:
            self.parts.append(content)

    def text(self):
        if not self.finished:
            raise ModelResponseError("missing")
        return "".join(self.parts)


def model_service_error_message(error, provider=LLM_PROVIDER, model_name=model):
    provider_name = (provider or "model").lower()
    if provider_name == "ollama":
        if isinstance(error, httpx.RemoteProtocolError):
            return (
                "Local Ollama stopped the response before generation completed. Restart Ollama, "
                "confirm that the configured model fits available memory, then retry."
            )
        if isinstance(error, APITimeoutError):
            return (
                "Local Ollama timed out while generating the response. Confirm that Ollama is still running, "
                "then retry. A smaller local model may help on limited hardware."
            )
        if isinstance(error, APIConnectionError):
            return (
                "Cannot reach the local Ollama service. Start it with `ollama serve`, verify "
                "`http://localhost:11434/api/tags`, then retry."
            )
        status_code = getattr(error, "status_code", None)
        if status_code == 404:
            return (
                f"Ollama is running, but the configured model `{model_name}` is unavailable. "
                f"Install it with `ollama pull {model_name}`, then retry."
            )
        return (
            "Ollama returned an unexpected service error"
            f"{f' (HTTP {status_code})' if status_code else ''}. Check the Ollama terminal and retry."
        )

    status_code = getattr(error, "status_code", None)
    return (
        f"The configured model service `{provider_name}` is unavailable"
        f"{f' (HTTP {status_code})' if status_code else ''}. Check its connection and credentials, then retry."
    )


def clean_model_output(text):
    """Remove tool-call residue and model-authored URLs before governance checks."""

    if not text:
        return ""
    cleaned = re.sub(r"```json\s*\{.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(
        r"\b(checklist_update|checklist_complete|plan_complete)\s*\([^)]*\)\s*(has been called)?[.\s]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"Call\s*`?(checklist_update|checklist_complete|plan_complete)`?\s*function.*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"`?(checklist_update|checklist_complete|plan_complete)`?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", "[verify through the relevant official source]", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class GovernedModelClient:
    """Make independent model requests without tools or provider-side history."""

    def __init__(
        self,
        *,
        completion_client=None,
        model_name=model,
        provider=LLM_PROVIDER,
        is_local=IS_LOCAL_LLM,
        timeout_seconds=MODEL_TIMEOUT_SECONDS,
        clock=time.monotonic,
    ):
        self._completion_client = completion_client or client
        self.model_name = model_name
        self.provider = provider
        self.is_local = is_local
        self.timeout_seconds = float(timeout_seconds)
        self._clock = clock
        self.last_request_capture = None
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero.")

    def _create_completion(self, messages, *, stream, request_slot):
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "temperature": MODEL_TEMPERATURE,
            "top_p": 0.8,
            "max_tokens": MODEL_MAX_TOKENS,
            "stream": stream,
        }
        if self.is_local:
            kwargs["seed"] = MODEL_SEED
        if self.provider.lower() == "deepseek":
            # The governed report contract budgets final text; V4 otherwise enables thinking by default.
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            completion_client = self._completion_client
            if request_slot.limits.enabled:
                configure = getattr(completion_client, "with_options", None)
                if not callable(configure):
                    raise ModelServiceError("The model client cannot enforce the configured request allowance.")
                # One reserved call must mean one HTTP attempt. Structural repairs reserve separately.
                completion_client = configure(max_retries=0)
            request_slot.consume_call()
            bind_submitted_messages(messages)
            return completion_client.chat.completions.create(**kwargs)
        except ModelAllowanceError as error:
            raise ModelServiceError(str(error)) from error
        except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as error:
            raise ModelServiceError(
                model_service_error_message(error, provider=self.provider, model_name=self.model_name)
            ) from error

    def _deadline_error(self):
        return ModelServiceError(
            f"Model generation exceeded the {self.timeout_seconds:g}-second total deadline. Retry the request."
        )

    def _raise_if_stream_deadline_exceeded(self, started_at, cancelled):
        if cancelled.is_set() or self._clock() - started_at > self.timeout_seconds:
            raise self._deadline_error()

    @staticmethod
    def _close_response_stream(stream_state, close_lock):
        with close_lock:
            response_stream = stream_state.get("response")
            if response_stream is None or stream_state.get("closed"):
                return
            close = getattr(response_stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:  # pragma: no cover - provider cleanup is implementation-specific
                    LOGGER.debug("Model stream cleanup failed (%s).", type(error).__name__)
                    # Closing while an iterator is executing can fail. Let the worker retry in its finally block.
                    return
            stream_state["closed"] = True

    def _consume_stream(self, messages, *, started_at, cancelled, stream_state, close_lock, request_slot):
        try:
            response_stream = self._create_completion(messages, stream=True, request_slot=request_slot)
            with close_lock:
                stream_state["response"] = response_stream
                cancelled_before_iteration = cancelled.is_set()
            if cancelled_before_iteration:
                self._close_response_stream(stream_state, close_lock)
                raise self._deadline_error()
            self._raise_if_stream_deadline_exceeded(started_at, cancelled)
            response = _StreamResponse()
            for chunk in response_stream:
                self._raise_if_stream_deadline_exceeded(started_at, cancelled)
                response.add(chunk)
            self._raise_if_stream_deadline_exceeded(started_at, cancelled)
        except ModelServiceError:
            raise
        except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as error:
            raise ModelServiceError(
                model_service_error_message(error, provider=self.provider, model_name=self.model_name)
            ) from error
        except Exception as error:
            raise ModelResponseError("invalid") from error
        finally:
            self._close_response_stream(stream_state, close_lock)
        self._raise_if_stream_deadline_exceeded(started_at, cancelled)
        return response.text()

    def _collect_stream(self, messages, request_slot):
        started_at = self._clock()
        wall_deadline = time.monotonic() + self.timeout_seconds
        cancelled = threading.Event()
        completed = threading.Event()
        close_lock = threading.Lock()
        stream_state = {"response": None, "closed": False}
        outcome = {}

        def consume():
            try:
                outcome["value"] = self._consume_stream(
                    messages,
                    started_at=started_at,
                    cancelled=cancelled,
                    stream_state=stream_state,
                    close_lock=close_lock,
                    request_slot=request_slot,
                )
            except Exception as error:
                outcome["error"] = error
            finally:
                request_slot.release()
                completed.set()

        worker = threading.Thread(target=consume, name="governed-model-stream", daemon=True)
        try:
            worker.start()
        except Exception:
            request_slot.release()
            raise
        remaining = max(0.0, wall_deadline - time.monotonic())
        if not completed.wait(remaining):
            cancelled.set()
            threading.Thread(
                target=self._close_response_stream,
                args=(stream_state, close_lock),
                name="governed-model-stream-close",
                daemon=True,
            ).start()
            raise self._deadline_error()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value", "")

    def _collect_completion(self, messages, request_slot):
        """Bound elapsed time, including SDK retries, without releasing a still-running worker."""
        started_at = self._clock()
        wall_deadline = time.monotonic() + self.timeout_seconds
        completed = threading.Event()
        outcome = {}

        def consume():
            try:
                response = self._create_completion(messages, stream=False, request_slot=request_slot)
                if self._clock() - started_at > self.timeout_seconds:
                    raise self._deadline_error()
                choice = _single_choice(response)
                message = getattr(choice, "message", None)
                content = _text_only_payload(message)
                _require_normal_stop(getattr(choice, "finish_reason", None))
                outcome["value"] = content
            except ModelServiceError as error:
                outcome["error"] = error
            except Exception:
                outcome["error"] = ModelResponseError("invalid")
            finally:
                request_slot.release()
                completed.set()

        worker = threading.Thread(target=consume, name="governed-model-completion", daemon=True)
        try:
            worker.start()
        except Exception:
            request_slot.release()
            raise
        if not completed.wait(max(0.0, wall_deadline - time.monotonic())):
            raise self._deadline_error()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value", "")

    def generate(self, prompt):
        self.last_request_capture = None
        messages = build_governed_messages(prompt)
        try:
            request_slot = acquire_model_slot()
        except (ModelAllowanceError, DeploymentConfigurationError) as error:
            raise ModelServiceError(str(error)) from error
        try:
            response_text = (
                self._collect_stream(messages, request_slot)
                if self.is_local
                else self._collect_completion(messages, request_slot)
            )
        except ModelResponseError as error:
            record_response_admission(error.reason)
        record_response_admission("stop")
        cleaned = (
            response_text
            if getattr(prompt, "output_contract", None) == SECTION_PROSE_OUTPUT_CONTRACT
            else clean_model_output(response_text)
        )
        if getattr(prompt, "output_contract", None) == SECTION_PROSE_OUTPUT_CONTRACT:
            try:
                cleaned.encode("utf-8")
            except UnicodeError:
                raise SectionProtocolError() from None
        if not cleaned:
            raise ModelServiceError("The model returned no usable report text. Retry the request.")
        if messages.submitted_binding is not None:
            self.last_request_capture = {**messages.submitted_binding, "response_sha256": text_sha256(cleaned)}
        return cleaned


_PREPARED_CALL_FIELDS = frozenset({"model", "messages", "temperature", "top_p", "max_tokens", "stream", "seed"})
_PREPARED_MESSAGES_BYTES = 256 * 1024
_PREPARED_CALL_ERRORS = frozenset(
    {"prepared_call_not_admitted", "prepared_call_plan_invalid", "prepared_call_client_invalid"}
)


class PreparedCallError(ModelServiceError):
    """Content-free rejection at the experimental controlled execution boundary."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in _PREPARED_CALL_ERRORS else "prepared_call_not_admitted"
        super().__init__(self.code)

    def __str__(self):
        return (
            self.code if type(self.code) is str and self.code in _PREPARED_CALL_ERRORS else "prepared_call_not_admitted"
        )

    def __repr__(self):
        return f"PreparedCallError({str(self)!r})"


def _prepared_call_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _snapshot_prepared_call(value):
    """Detach and validate one exact builtin-only SDK plan; never normalize text."""
    try:
        if type(value) is not dict:
            raise ValueError
        value = value.copy()
        if any(type(key) is not str for key in value) or set(value) != _PREPARED_CALL_FIELDS:
            raise ValueError
        messages = value["messages"]
        if type(messages) is not list or len(messages) != 2:
            raise ValueError
        messages = messages.copy()
        for index, role in enumerate(("system", "user")):
            message = messages[index]
            if type(message) is not dict:
                raise ValueError
            message = message.copy()
            if any(type(key) is not str for key in message) or set(message) != {"role", "content"}:
                raise ValueError
            if type(message["role"]) is not str or message["role"] != role:
                raise ValueError
            content = message["content"]
            if type(content) is not str or not content or len(content) > _PREPARED_MESSAGES_BYTES:
                raise ValueError
            messages[index] = message
        value["messages"] = messages
        name = value["model"]
        if type(name) is not str or not name or len(name) > 256:
            raise ValueError
        if name != name.strip() or not name.isprintable() or len(name.encode("utf-8")) > 256:
            raise ValueError
        temperature = value["temperature"]
        if type(temperature) is not float or not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
            raise ValueError
        if type(value["top_p"]) is not float or value["top_p"] != 0.8 or value["stream"] is not True:
            raise ValueError
        if type(value["max_tokens"]) is not int or not 1 <= value["max_tokens"] <= 2**31 - 1:
            raise ValueError
        if type(value["seed"]) is not int or not 0 <= value["seed"] <= 2**31 - 1:
            raise ValueError
        if len(_prepared_call_json(messages).encode("utf-8")) > _PREPARED_MESSAGES_BYTES:
            raise ValueError
        encoded = _prepared_call_json(value)
        if len(encoded.encode("utf-8")) > _PREPARED_MESSAGES_BYTES + 8192:
            raise ValueError
        return encoded
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        raise PreparedCallError("prepared_call_plan_invalid") from None


def _prepared_local_client_identity(completion_client):
    """Check the supplied destination, without configuring a client or doing I/O.

    A trusted dependency must still establish transport/proxy behavior. A local
    URL is not proof about a custom transport, model identity or effective budget.
    """
    try:
        endpoint = completion_client.base_url
        if type(endpoint) not in (str, httpx.URL):
            raise ValueError
        endpoint = str(endpoint)
        if validate_model_endpoint(endpoint) != endpoint or not is_loopback_model_endpoint(endpoint):
            raise ValueError
        http_client = completion_client._client
        if (
            http_client.follow_redirects is not False
            or http_client.trust_env is not False
            or not callable(completion_client.with_options)
        ):
            raise ValueError
        return endpoint, http_client
    except Exception:
        raise PreparedCallError("prepared_call_client_invalid") from None


class _PreparedCallAdmission:
    """Opaque process-local, single-use capability; contains no request data."""

    __slots__ = ()

    def __repr__(self):
        return "<prepared-call admission>"

    def __reduce__(self):
        raise TypeError("Prepared-call admissions cannot be serialized.")

    def __copy__(self):
        raise TypeError("Prepared-call admissions cannot be copied.")

    def __deepcopy__(self, memo):
        raise TypeError("Prepared-call admissions cannot be copied.")


def _new_prepared_call_gate():
    """Return a disconnected consumer/issuer pair, not a runtime attestation.

    The production consumer below deliberately discards its issuer. Tests may
    install their own isolated consumer to exercise mechanics with fake clients;
    those tokens cannot authorize the production consumer. This private seam is
    an application boundary, not isolation against arbitrary Python execution.
    """
    issued = {}
    lock = threading.Lock()

    def issue(kwargs, completion_client):
        encoded = _snapshot_prepared_call(kwargs)
        endpoint, http_client = _prepared_local_client_identity(completion_client)
        capability = _PreparedCallAdmission()
        with lock:
            issued[capability] = (encoded, completion_client, endpoint, http_client)
        return capability

    def take(capability, kwargs, completion_client):
        if type(capability) is not _PreparedCallAdmission:
            raise PreparedCallError("prepared_call_not_admitted") from None
        with lock:
            admitted = issued.pop(capability, None)
        if admitted is None:
            raise PreparedCallError("prepared_call_not_admitted") from None
        encoded, admitted_client, endpoint, http_client = admitted
        if completion_client is not admitted_client or _snapshot_prepared_call(kwargs) != encoded:
            raise PreparedCallError("prepared_call_not_admitted") from None
        current_endpoint, current_http_client = _prepared_local_client_identity(completion_client)
        if current_endpoint != endpoint or current_http_client is not http_client:
            raise PreparedCallError("prepared_call_not_admitted") from None
        return encoded, endpoint, http_client

    return take, issue


# No app/config issuer exists. Offline hashes, booleans and rehashed summaries
# cannot register a capability here. Adding real admission requires new work.
_take_prepared_call_admission = _new_prepared_call_gate()[0]


class _PreparedLocalCall(GovernedModelClient):
    """One execution's state, reusing the governed stream lifetime and deadline."""

    def __init__(self, encoded, completion_client, endpoint, http_client, timeout_seconds, clock):
        # Do not invoke the ordinary constructor's configured-client fallback.
        self._kwargs = json.loads(encoded)
        self._completion_client = completion_client
        self._endpoint = endpoint
        self._http_client = http_client
        self.model_name = self._kwargs["model"]
        self.provider = "ollama"
        self.timeout_seconds = timeout_seconds
        self._clock = clock
        self.submitted_kwargs_sha256 = None

    def _consume_stream(self, messages, **kwargs):
        self._started_at = kwargs["started_at"]
        self._cancelled = kwargs["cancelled"]
        try:
            return super()._consume_stream(messages, **kwargs)
        except PreparedCallError as error:
            raise PreparedCallError(error.code) from None
        except ModelResponseError as error:
            raise ModelResponseError(error.reason) from None
        except ModelServiceError as error:
            # Keep the fixed deadline diagnostic; strip any provider-originated
            # content and exception chains, including iterator-time failures.
            deadline = self._deadline_error()
            if str(error) == str(deadline):
                raise deadline from None
            raise ModelServiceError("The controlled local model request failed.") from None

    def _create_completion(self, messages, *, stream, request_slot):
        self._raise_if_stream_deadline_exceeded(self._started_at, self._cancelled)
        try:
            configured = self._completion_client.with_options(max_retries=0)
            endpoint, http_client = _prepared_local_client_identity(configured)
            if (
                endpoint != self._endpoint
                or http_client is not self._http_client
                or type(configured.max_retries) is not int
                or configured.max_retries != 0
            ):
                raise PreparedCallError("prepared_call_client_invalid")
            self._raise_if_stream_deadline_exceeded(self._started_at, self._cancelled)
            create = configured.chat.completions.create
            if not callable(create):
                raise PreparedCallError("prepared_call_client_invalid")
            kwargs = {**self._kwargs, "messages": messages}
            request_slot.consume_call()
            self._raise_if_stream_deadline_exceeded(self._started_at, self._cancelled)
            bind_submitted_messages(messages)
            self.submitted_kwargs_sha256 = text_sha256(_prepared_call_json(kwargs))
            try:
                return create(**kwargs)
            except Exception:
                raise ModelServiceError("The controlled local model request failed.") from None
        except ModelServiceError:
            raise
        except ModelAllowanceError:
            raise ModelServiceError("The controlled local model allowance is unavailable.") from None
        except Exception:
            # SDK errors can contain the private model label/request/response.
            # The controlled entry never exposes provider exception chains.
            raise ModelServiceError("The controlled local model request failed.") from None


class ControlledLocalModelExecutor:
    """Default-denied experimental executor; does not enable automatic repair.

    Supply exact prospective kwargs, a process-local admission and an explicit
    local SDK dependency. There is currently no production admission issuer.
    The result is raw normally-stopped text, for downstream section validation;
    no budget, runtime-equivalence or report-acceptance claim is made here.
    """

    def __init__(self, *, timeout_seconds=MODEL_TIMEOUT_SECONDS, clock=time.monotonic):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero.")
        self.timeout_seconds = float(timeout_seconds)
        self._clock = clock
        self.last_request_capture = None
        self.last_call_capture = None

    def execute(self, completion_kwargs, *, admission=None, completion_client=None):
        self.last_request_capture = None
        self.last_call_capture = None
        encoded, endpoint, http_client = _take_prepared_call_admission(admission, completion_kwargs, completion_client)
        call = _PreparedLocalCall(encoded, completion_client, endpoint, http_client, self.timeout_seconds, self._clock)
        messages = CapturedMessages(call._kwargs["messages"])
        try:
            request_slot = acquire_model_slot()
        except (ModelAllowanceError, DeploymentConfigurationError):
            raise ModelServiceError("The controlled local model allowance is unavailable.") from None
        try:
            response_text = call._collect_stream(messages, request_slot)
        except ModelResponseError as error:
            record_response_admission(error.reason)
        except ModelAllowanceError:
            raise ModelServiceError("The controlled local model allowance is unavailable.") from None
        record_response_admission("stop")
        try:
            response_text.encode("utf-8")
        except UnicodeError:
            raise SectionProtocolError() from None
        if not response_text:
            raise ModelServiceError("The model returned no usable report text. Retry the request.")
        if messages.submitted_binding is not None and call.submitted_kwargs_sha256 is not None:
            self.last_request_capture = {
                **messages.submitted_binding,
                "response_sha256": text_sha256(response_text),
            }
            self.last_call_capture = {
                "schema": "controlled-local-sdk-call-binding-v1",
                "kwargs_sha256": call.submitted_kwargs_sha256,
                "response_sha256": text_sha256(response_text),
            }
        return response_text
