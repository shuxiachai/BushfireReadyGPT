import json
import os
import re
import time
from abc import ABC, abstractmethod

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from src.config import (
    IS_LOCAL_LLM,
    LLM_PROVIDER,
    MODEL_MAX_TOKENS,
    MODEL_SEED,
    MODEL_TEMPERATURE,
    client,
    model,
)
from src.utils import create_thread, get_assistant, load_config

THREAD_MESSAGES = {}
THREAD_LAST_USED = {}


def _positive_env_integer(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer.") from error
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


THREAD_TTL_SECONDS = _positive_env_integer("BUSHFIRE_THREAD_TTL_SECONDS", 3600)
THREAD_MAX_COUNT = _positive_env_integer("BUSHFIRE_THREAD_MAX_COUNT", 128)
THREAD_MAX_MESSAGES = _positive_env_integer("BUSHFIRE_THREAD_MAX_MESSAGES", 64)


def prune_thread_messages(*, now=None):
    current = time.monotonic() if now is None else float(now)
    for thread_id in list(THREAD_LAST_USED):
        if thread_id not in THREAD_MESSAGES:
            THREAD_LAST_USED.pop(thread_id, None)
    stale_ids = [
        thread_id
        for thread_id in THREAD_MESSAGES
        if current - THREAD_LAST_USED.get(thread_id, current) >= THREAD_TTL_SECONDS
    ]
    for thread_id in stale_ids:
        THREAD_MESSAGES.pop(thread_id, None)
        THREAD_LAST_USED.pop(thread_id, None)
    overflow = len(THREAD_MESSAGES) - THREAD_MAX_COUNT
    if overflow > 0:
        oldest = sorted(
            THREAD_MESSAGES,
            key=lambda thread_id: THREAD_LAST_USED.get(thread_id, float("-inf")),
        )[:overflow]
        for thread_id in oldest:
            THREAD_MESSAGES.pop(thread_id, None)
            THREAD_LAST_USED.pop(thread_id, None)


def clear_thread_messages(thread_id):
    THREAD_MESSAGES.pop(thread_id, None)
    THREAD_LAST_USED.pop(thread_id, None)


def replace_thread_messages(thread_id, messages):
    THREAD_MESSAGES[thread_id] = list(messages or [])[-THREAD_MAX_MESSAGES:]
    THREAD_LAST_USED[thread_id] = time.monotonic()
    prune_thread_messages()


def _thread_messages(thread_id):
    prune_thread_messages()
    THREAD_MESSAGES.setdefault(thread_id, [])
    THREAD_LAST_USED[thread_id] = time.monotonic()
    prune_thread_messages()
    return THREAD_MESSAGES.setdefault(thread_id, [])


def _append_thread_message(thread_id, message):
    messages = _thread_messages(thread_id)
    messages.append(message)
    if len(messages) > THREAD_MAX_MESSAGES:
        del messages[: len(messages) - THREAD_MAX_MESSAGES]
    THREAD_LAST_USED[thread_id] = time.monotonic()
    return messages


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
            f"Ollama returned an unexpected service error"
            f"{f' (HTTP {status_code})' if status_code else ''}. Check the Ollama terminal and retry."
        )

    status_code = getattr(error, "status_code", None)
    return (
        f"The configured model service `{provider_name}` is unavailable"
        f"{f' (HTTP {status_code})' if status_code else ''}. Check its connection and credentials, then retry."
    )


def _raise_model_service_error(error):
    raise ModelServiceError(model_service_error_message(error)) from error


def clean_model_output(text):
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
        r"Call\s*`?(checklist_update|checklist_complete|plan_complete)`?\s*function.*", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"`?(checklist_update|checklist_complete|plan_complete)`?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", "[verify through the relevant official source]", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class Assistant(ABC):
    def __init__(self, config_path, update_assistant):
        self.config = load_config(config_path)
        self.function_dict = {}
        self.update_assistant = update_assistant
        self.assistant = get_assistant(self.config, self.initialize_instructions)
        self.visualizations = []

    @abstractmethod
    def initialize_instructions(self):
        pass

    def add_assistant_message(self, message, thread_id):
        _append_thread_message(thread_id, {"role": "assistant", "content": message})

    def _get_messages(self, thread_id):
        return _thread_messages(thread_id)

    def _create_completion(self, messages, stream=False, allow_tools=True):
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": MODEL_TEMPERATURE,
            "top_p": 0.8,
            "max_tokens": MODEL_MAX_TOKENS,
            "stream": stream,
        }
        if IS_LOCAL_LLM:
            kwargs["seed"] = MODEL_SEED
        if allow_tools and self.assistant.tools and not IS_LOCAL_LLM:
            kwargs["tools"] = self.assistant.tools
            kwargs["tool_choice"] = "auto"
        try:
            return client.chat.completions.create(**kwargs)
        except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as error:
            _raise_model_service_error(error)

    def _stream_text_completion(self, messages, allow_tools=True):
        """Collect streamed model text without exposing it before governance checks."""
        try:
            response_stream = self._create_completion(
                messages,
                stream=True,
                allow_tools=allow_tools,
            )
            full_response = ""
            for chunk in response_stream:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    full_response += content
            return full_response
        except ModelServiceError:
            raise
        except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as error:
            _raise_model_service_error(error)

    def _discard_failed_user_message(self, stored_messages, user_message):
        if (
            user_message
            and stored_messages
            and stored_messages[-1].get("role") == "user"
            and stored_messages[-1].get("content") == user_message
        ):
            stored_messages.pop()

    def get_assistant_response(self, user_message=None, thread_id=None, allow_tools=True):
        if thread_id is None:
            thread_id = create_thread().id

        stored_messages = self._get_messages(thread_id)
        if user_message:
            stored_messages = _append_thread_message(
                thread_id,
                {"role": "user", "content": user_message},
            )

        messages = [{"role": "system", "content": self.assistant.instructions}] + stored_messages
        if IS_LOCAL_LLM:
            try:
                full_response = clean_model_output(self._stream_text_completion(messages, allow_tools=allow_tools))
            except ModelServiceError:
                self._discard_failed_user_message(stored_messages, user_message)
                raise
            _append_thread_message(thread_id, {"role": "assistant", "content": full_response})
            return full_response, None, []

        try:
            response = self._create_completion(messages, allow_tools=allow_tools).choices[0].message
        except ModelServiceError:
            self._discard_failed_user_message(stored_messages, user_message)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls and allow_tools:
            assistant_message = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in tool_calls
                ],
            }
            _append_thread_message(thread_id, assistant_message)

            tool_outputs = []
            for tool_call in tool_calls:
                output = self.on_tool_call_created(tool_call)
                if output == "Change Thread":
                    return "", None, []
                output_text = output if isinstance(output, str) else str(output)
                _append_thread_message(
                    thread_id,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": output_text or "Success!",
                    },
                )
                tool_outputs.append({"tool_call_id": tool_call.id, "output": output_text or "Success!"})
            return response.content or "", None, tool_outputs

        full_response = clean_model_output(response.content or "")
        _append_thread_message(thread_id, {"role": "assistant", "content": full_response})
        return full_response, None, []

    def respond_to_tool_output(self, thread_id, run_id, tool_outputs):
        if not tool_outputs:
            return ""

        stored_messages = self._get_messages(thread_id)
        messages = [{"role": "system", "content": self.assistant.instructions}] + stored_messages
        if IS_LOCAL_LLM:
            full_response = clean_model_output(self._stream_text_completion(messages))
        else:
            response = self._create_completion(messages).choices[0].message
            full_response = clean_model_output(response.content or "")
        _append_thread_message(thread_id, {"role": "assistant", "content": full_response})
        return full_response

    def on_tool_call_created(self, tool):
        function = self.function_dict.get(tool.function.name)
        if function is None:
            return f"Tool '{tool.function.name}' is not available."
        function_args = json.loads(tool.function.arguments or "{}")
        return function(**function_args)
