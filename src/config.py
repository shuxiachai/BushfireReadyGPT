from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
IS_LOCAL_LLM = LLM_PROVIDER == "ollama"

if LLM_PROVIDER == "ollama":
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    client = OpenAI(base_url=base_url, api_key=os.environ.get("OLLAMA_API_KEY", "ollama"))
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
elif LLM_PROVIDER == "openai":
    client = OpenAI()
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL is not set. Add OPENAI_MODEL=<model name> to your .env file.")
elif LLM_PROVIDER == "openrouter":
    client = OpenAI(
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    model = os.environ.get("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct")
elif LLM_PROVIDER == "deepseek":
    client = OpenAI(
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
    )
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
else:
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")

# create a directory for saving the chat history
if not os.path.exists("chat_history"):
    os.makedirs("chat_history")

chat_history_path = "chat_history/"
