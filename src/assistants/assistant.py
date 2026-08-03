from src.utils import get_assistant, create_thread, load_config
from src.config import client, model, IS_LOCAL_LLM, LLM_PROVIDER
import json
import streamlit as st
from abc import ABC, abstractmethod
import re
from openai import APIConnectionError, APIStatusError, APITimeoutError

THREAD_MESSAGES = {}


class ModelServiceError(RuntimeError):
    """A model-provider failure that is safe to display in the UI."""


def model_service_error_message(error, provider=LLM_PROVIDER, model_name=model):
    provider_name = (provider or "model").lower()
    if provider_name == "ollama":
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
    cleaned = re.sub(r"\b(checklist_update|checklist_complete|plan_complete)\s*\([^)]*\)\s*(has been called)?[.\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Call\s*`?(checklist_update|checklist_complete|plan_complete)`?\s*function.*", "", cleaned, flags=re.IGNORECASE)
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
        THREAD_MESSAGES.setdefault(thread_id, []).append({"role": "assistant", "content": message})

    def _get_messages(self, thread_id):
        THREAD_MESSAGES.setdefault(thread_id, [])
        return THREAD_MESSAGES[thread_id]

    def _create_completion(self, messages, stream=False):
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "top_p": 0.8,
            "stream": stream,
        }
        if self.assistant.tools and not IS_LOCAL_LLM:
            kwargs["tools"] = self.assistant.tools
            kwargs["tool_choice"] = "auto"
        try:
            return client.chat.completions.create(**kwargs)
        except (APIConnectionError, APITimeoutError, APIStatusError) as error:
            _raise_model_service_error(error)

    def _stream_text_completion(self, messages):
        try:
            response_stream = self._create_completion(messages, stream=True)
            full_response = ""
            placeholder = st.empty()
            for chunk in response_stream:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    full_response += content
                    placeholder.markdown(full_response)
            return full_response
        except ModelServiceError:
            raise
        except (APIConnectionError, APITimeoutError, APIStatusError) as error:
            _raise_model_service_error(error)

    def _discard_failed_user_message(self, stored_messages, user_message):
        if (
            user_message
            and stored_messages
            and stored_messages[-1].get("role") == "user"
            and stored_messages[-1].get("content") == user_message
        ):
            stored_messages.pop()

    def get_assistant_response(self, user_message=None, thread_id=None):
        if thread_id is None:
            thread_id = create_thread().id

        stored_messages = self._get_messages(thread_id)
        if user_message:
            stored_messages.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": self.assistant.instructions}] + stored_messages
        if IS_LOCAL_LLM:
            try:
                full_response = clean_model_output(self._stream_text_completion(messages))
            except ModelServiceError:
                self._discard_failed_user_message(stored_messages, user_message)
                raise
            stored_messages.append({"role": "assistant", "content": full_response})
            return full_response, None, []

        try:
            response = self._create_completion(messages).choices[0].message
        except ModelServiceError:
            self._discard_failed_user_message(stored_messages, user_message)
            raise

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
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
            stored_messages.append(assistant_message)

            tool_outputs = []
            for tool_call in tool_calls:
                output = self.on_tool_call_created(tool_call)
                if output == "Change Thread":
                    return "", None, []
                output_text = output if isinstance(output, str) else str(output)
                stored_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": output_text or "Success!",
                    }
                )
                tool_outputs.append({"tool_call_id": tool_call.id, "output": output_text or "Success!"})
            return response.content or "", None, tool_outputs

        full_response = clean_model_output(response.content or "")
        stored_messages.append({"role": "assistant", "content": full_response})
        st.markdown(full_response)
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
        stored_messages.append({"role": "assistant", "content": full_response})
        st.markdown(full_response)

        with open("chat_history/tools.txt", "a", encoding="utf-8") as f:
            f.write("\n\n\n\n**Tool Outputs**\n")
            for tool_output in tool_outputs:
                f.write(tool_output["output"])
            f.write("\n**LLM Response**\n")
            f.write(full_response)
            f.write("\n")
        return full_response

    def on_tool_call_created(self, tool):
        function = self.function_dict.get(tool.function.name)
        if function is None:
            return f"Tool '{tool.function.name}' is not available."
        function_args = json.loads(tool.function.arguments or "{}")
        return function(**function_args)
