from src.utils import get_assistant, create_thread, load_config
from src.config import client, model, IS_LOCAL_LLM
import json
import streamlit as st
from abc import ABC, abstractmethod
import re

THREAD_MESSAGES = {}


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
        return client.chat.completions.create(**kwargs)

    def _stream_text_completion(self, messages):
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

    def get_assistant_response(self, user_message=None, thread_id=None):
        if thread_id is None:
            thread_id = create_thread().id

        stored_messages = self._get_messages(thread_id)
        if user_message:
            stored_messages.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": self.assistant.instructions}] + stored_messages
        if IS_LOCAL_LLM:
            full_response = clean_model_output(self._stream_text_completion(messages))
            stored_messages.append({"role": "assistant", "content": full_response})
            return full_response, None, []

        response = self._create_completion(messages).choices[0].message

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
