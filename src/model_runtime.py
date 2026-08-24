"""Stateless, tool-free model access for governed report generation."""

from __future__ import annotations

import logging
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
    model,
)

GOVERNED_MODEL_SYSTEM_PROMPT = """You are the governed report-generation engine for BushfireReadyGPT.
Process only the current request. Do not retain conversational history, call tools, emit tool-call syntax, or
claim that you accessed live emergency information. Return only the requested English Markdown report. Follow
the safety, evidence, structure and human-review requirements in the current request exactly."""
LOGGER = logging.getLogger(__name__)


class ModelServiceError(RuntimeError):
    """A model-provider failure that is safe to display in the UI."""


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
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

    def _create_completion(self, messages, *, stream):
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
        try:
            return self._completion_client.chat.completions.create(**kwargs)
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
            stream_state["closed"] = True
            close = getattr(response_stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:  # pragma: no cover - provider cleanup is implementation-specific
                    LOGGER.debug("Model stream cleanup failed (%s).", type(error).__name__)

    def _consume_stream(self, messages, *, started_at, cancelled, stream_state, close_lock):
        try:
            response_stream = self._create_completion(messages, stream=True)
            with close_lock:
                stream_state["response"] = response_stream
                cancelled_before_iteration = cancelled.is_set()
            if cancelled_before_iteration:
                self._close_response_stream(stream_state, close_lock)
                raise self._deadline_error()
            self._raise_if_stream_deadline_exceeded(started_at, cancelled)
            parts = []
            for chunk in response_stream:
                self._raise_if_stream_deadline_exceeded(started_at, cancelled)
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    parts.append(content)
            self._raise_if_stream_deadline_exceeded(started_at, cancelled)
        except ModelServiceError:
            raise
        except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as error:
            raise ModelServiceError(
                model_service_error_message(error, provider=self.provider, model_name=self.model_name)
            ) from error
        finally:
            self._close_response_stream(stream_state, close_lock)
        self._raise_if_stream_deadline_exceeded(started_at, cancelled)
        return "".join(parts)

    def _collect_stream(self, messages):
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
                )
            except Exception as error:
                outcome["error"] = error
            finally:
                completed.set()

        worker = threading.Thread(target=consume, name="governed-model-stream", daemon=True)
        worker.start()
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

    def generate(self, prompt):
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            raise ValueError("A governed model prompt is required.")
        messages = [
            {"role": "system", "content": GOVERNED_MODEL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ]
        if self.is_local:
            response_text = self._collect_stream(messages)
        else:
            response = self._create_completion(messages, stream=False)
            choices = getattr(response, "choices", None) or []
            message = getattr(choices[0], "message", None) if choices else None
            response_text = getattr(message, "content", None) or ""
        cleaned = clean_model_output(response_text)
        if not cleaned:
            raise ModelServiceError("The model returned no usable report text. Retry the request.")
        return cleaned
