from src.config import client, model, IS_LOCAL_LLM
import yaml
import time
import streamlit as st
from types import SimpleNamespace
from uuid import uuid4

TEXT_CURSOR = "..."


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config


def get_assistant(config, initialize_instructions):
    name = config["name"]
    instructions = initialize_instructions()
    if IS_LOCAL_LLM:
        instructions += """

LOCAL OLLAMA MODE OVERRIDE:
You are running as a direct conversational assistant, not as an OpenAI Assistants tool-calling agent.
Never mention function calls, JSON tool calls, checklist_update, checklist_complete, plan_complete, thread IDs, internal tools, or implementation details.
Do not pretend to call functions.
Use English for final reports and product-style outputs unless the user explicitly requests another language.
Be practical and decisive.
If the user asks for advice, provide useful advice directly.
If information is missing, ask at most one focused follow-up question, then continue with reasonable assumptions.
For this project, act as BushfireReadyGPT: an Australian bushfire preparedness and community resilience assistant.
Your default output should help the user get a concrete result. For campus or community preparedness requests, produce a polished report-style answer with:
1. Title
2. Purpose and assumptions
3. Risk context
4. Immediate action plan
5. Roles and responsibilities
6. Evacuation and assembly planning
7. Training and communication plan
8. Short-term timeline, preferably today, this week, this month, and before the next fire season
9. Practical checklist
10. Official Australian sources to verify
11. Safety disclaimer
Avoid slow multi-year timelines unless the user explicitly asks for long-term planning.
Do not invent official URLs. If you are not certain about a URL, name the official source and tell the user to search the official site.
Do not present gymnasiums, lecture halls, sports fields, carparks, or other places as confirmed safe assembly points. Present them only as candidate assembly point types that must be checked and approved by campus management and official emergency guidance.
Include relevant state or local context such as seasonal fire risk, smoke and heat exposure, road disruption, power/communications outage, surrounding vegetation, and the need to monitor official state or territory emergency services and Bureau of Meteorology warnings.
Always include a safety note that live warnings, fire bans, evacuation orders, and emergency instructions must come from official state or territory emergency services.
"""
    tools = populate_tools(config)
    return SimpleNamespace(id=f"local-assistant-{uuid4()}", name=name, instructions=instructions, tools=tools or [])


def populate_tools(config):
    tools = []
    if "available_functions" not in config:
        return None
    for tool_name, tool_meta_data in config["available_functions"].items():
        tool = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_meta_data["description"],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": tool_meta_data["required"],
                },
            },
        }
        if tool_meta_data["parameters"]:
            for param_name, param_meta_data in tool_meta_data["parameters"].items():
                tool["function"]["parameters"]["properties"][param_name] = {
                    "type": param_meta_data["type"],
                    "description": param_meta_data["description"],
                }
        tools.append(tool)
    return tools


def create_thread():
    return SimpleNamespace(id=f"local-thread-{uuid4()}")


def add_appendix(response: str, appendix_path: str):
    with open(appendix_path, "r", encoding="utf-8") as f:
        appendix = f.read()
    return response + appendix


def get_llm_response(messages, top_p=0.95, max_tokens=256, temperature=0.7):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        top_p=top_p,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


def get_openai_response(messages, top_p=0.95, max_tokens=256, temperature=0.7):
    return get_llm_response(messages, top_p=top_p, max_tokens=max_tokens, temperature=temperature)


def create_text_stream(text):
    yield text


def stream_static_text(text):
    st.write_stream(create_text_stream(text))


def get_conversation_summary(messages, summary_instructions="**Please summarize the previous conversation in a few sentences.**", max_tokens=512):
    messages += [{"role": "system", "content": summary_instructions}]
    return get_llm_response(messages, max_tokens=max_tokens)


def retry_on_generation_error(messages, response, possible_actions, exact_match=False):
    if exact_match:
        while response not in possible_actions:
            response = get_llm_response(messages, temperature=1)
    else:
        while not any(action in response for action in possible_actions):
            response = get_llm_response(messages, temperature=1)
    return response


def get_llm_response_with_retries(messages, possible_actions, top_p=0.95, max_tokens=256, temperature=0.7, exact_match=False):
    response = get_llm_response(messages, top_p=top_p, max_tokens=max_tokens, temperature=temperature)
    return retry_on_generation_error(messages, response, possible_actions, exact_match=exact_match)


def get_openai_response_with_retries(messages, possible_actions, top_p=0.95, max_tokens=256, temperature=0.7, exact_match=False):
    return get_llm_response_with_retries(
        messages,
        possible_actions,
        top_p=top_p,
        max_tokens=max_tokens,
        temperature=temperature,
        exact_match=exact_match,
    )
