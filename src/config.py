import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_loopback_model_endpoint(endpoint):
    """Return True only when an endpoint resolves syntactically to a loopback host.

    This deliberately does not treat a provider name (including ``ollama``) as a
    locality signal. Host aliases other than localhost are also rejected because
    resolving DNS here would make this check environment-dependent.
    """

    value = str(endpoint or "").strip()
    if not value:
        return False

    direct_host = value.strip("[]")
    try:
        return ipaddress.ip_address(direct_host.split("%", 1)[0]).is_loopback
    except ValueError:
        pass

    candidate = value if "://" in value else f"//{value}"
    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        return False
    if not host:
        return False
    normalised_host = host.rstrip(".").lower()
    if normalised_host == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalised_host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _env_true(name):
    return os.environ.get(name, "").strip().lower() == "true"


def _positive_number(name, default, *, integer=False, allow_zero=False):
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value) if integer else float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a valid {'integer' if integer else 'number'}.") from error
    minimum_ok = value >= 0 if allow_zero else value > 0
    if not minimum_ok:
        qualifier = "zero or greater" if allow_zero else "greater than zero"
        raise RuntimeError(f"{name} must be {qualifier}.")
    return value


def safe_model_endpoint_display(endpoint):
    """Return a destination label without credentials, query values or fragments."""

    value = str(endpoint or "").strip()
    if not value:
        return "<not configured>"
    candidate = value if "://" in value else f"//{value}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<configured endpoint>"
    if not hostname:
        return "<configured endpoint>"
    host_label = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{host_label}:{port}" if port is not None else host_label
    prefix = f"{parsed.scheme}://" if parsed.scheme else ""
    return f"{prefix}{authority}{parsed.path or ''}"


def validate_model_endpoint(endpoint):
    """Reject malformed endpoints and plaintext transport outside loopback."""

    value = str(endpoint or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise RuntimeError("The configured model endpoint is not a valid URL.") from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("The configured model endpoint must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("The configured model endpoint must not contain credentials, a query or a fragment.")
    if not is_loopback_model_endpoint(value) and parsed.scheme != "https":
        raise RuntimeError("External model endpoints must use HTTPS; plaintext HTTP is allowed only for loopback.")
    return value


LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
MODEL_TIMEOUT_SECONDS = _positive_number("BUSHFIRE_MODEL_TIMEOUT_SECONDS", 120.0)
MODEL_MAX_TOKENS = _positive_number("BUSHFIRE_MODEL_MAX_TOKENS", 4096, integer=True)
MODEL_TEMPERATURE = _positive_number(
    "BUSHFIRE_MODEL_TEMPERATURE",
    0.2,
    allow_zero=True,
)
MODEL_SEED = _positive_number(
    "BUSHFIRE_MODEL_SEED",
    42,
    integer=True,
    allow_zero=True,
)
MODEL_MAX_RETRIES = _positive_number(
    "BUSHFIRE_MODEL_MAX_RETRIES",
    1,
    integer=True,
    allow_zero=True,
)
_CLIENT_SAFETY_OPTIONS = {
    "timeout": MODEL_TIMEOUT_SECONDS,
    "max_retries": MODEL_MAX_RETRIES,
}

if LLM_PROVIDER == "ollama":
    MODEL_ENDPOINT = validate_model_endpoint(os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"))
    client = OpenAI(
        base_url=MODEL_ENDPOINT,
        api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
        **_CLIENT_SAFETY_OPTIONS,
    )
    model = os.environ.get("OLLAMA_MODEL", "bushfire-ready-qwen")
elif LLM_PROVIDER == "openai":
    MODEL_ENDPOINT = validate_model_endpoint(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    client = OpenAI(base_url=MODEL_ENDPOINT, **_CLIENT_SAFETY_OPTIONS)
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL is not set. Add OPENAI_MODEL=<model name> to your .env file.")
elif LLM_PROVIDER == "openrouter":
    MODEL_ENDPOINT = validate_model_endpoint(os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    client = OpenAI(
        base_url=MODEL_ENDPOINT,
        api_key=os.environ["OPENROUTER_API_KEY"],
        **_CLIENT_SAFETY_OPTIONS,
    )
    model = os.environ.get("OPENROUTER_MODEL", "qwen/qwen-2.5-72b-instruct")
elif LLM_PROVIDER == "deepseek":
    MODEL_ENDPOINT = validate_model_endpoint(os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    client = OpenAI(
        base_url=MODEL_ENDPOINT,
        api_key=os.environ["DEEPSEEK_API_KEY"],
        **_CLIENT_SAFETY_OPTIONS,
    )
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
else:
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")

MODEL_ENDPOINT_IS_LOCAL = is_loopback_model_endpoint(MODEL_ENDPOINT)
MODEL_ENDPOINT_DISPLAY = safe_model_endpoint_display(MODEL_ENDPOINT)
IS_LOCAL_LLM = MODEL_ENDPOINT_IS_LOCAL
EXTERNAL_MODEL_ALLOWED = _env_true("BUSHFIRE_ALLOW_EXTERNAL_MODEL")

chat_history_path = str(PROJECT_ROOT / "chat_history")
