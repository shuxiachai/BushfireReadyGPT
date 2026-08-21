from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from src.data_paths import get_data_paths
from src.rag.errors import RagError


def _positive_int(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RagError("rag_config_invalid", f"{name} must be a positive integer.") from error
    if isinstance(value, bool) or value < 1:
        raise RagError("rag_config_invalid", f"{name} must be a positive integer.")
    return value


def _score(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RagError("rag_config_invalid", f"{name} must be a number between -1 and 1.") from error
    if not -1 <= value <= 1:
        raise RagError("rag_config_invalid", f"{name} must be a number between -1 and 1.")
    return value


def _boolean(name, default):
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RagError("rag_config_invalid", f"{name} must be true or false.")


def _unit_interval(name, default):
    value = _score(name, default)
    if not 0 <= value <= 1:
        raise RagError("rag_config_invalid", f"{name} must be a number between 0 and 1.")
    return value


def _loopback_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
    except ValueError as error:
        raise RagError("rag_config_invalid", "The RAG embedding endpoint is not a valid URL.") from error
    if parsed.scheme not in {"http", "https"} or not host:
        raise RagError("rag_config_invalid", "The RAG embedding endpoint must be an absolute HTTP URL.")
    normalised = host.rstrip(".").lower()
    if normalised == "localhost":
        return
    try:
        if ipaddress.ip_address(normalised.split("%", 1)[0]).is_loopback:
            return
    except ValueError:
        pass
    raise RagError(
        "rag_external_embedding_blocked",
        "RAG embeddings are local-only in this prototype; configure a loopback Ollama endpoint.",
    )


@dataclass(frozen=True)
class RagSettings:
    rag_dir: Path
    sources_path: Path
    raw_dir: Path
    index_dir: Path
    embedding_base_url: str
    embedding_model: str
    embedding_timeout_seconds: int
    embedding_batch_size: int
    top_k: int
    score_threshold: float
    collection_name: str = "bushfire_official_knowledge_v1"
    enabled: bool = True
    candidate_multiplier: int = 4
    dense_weight: float = 0.65
    rrf_k: int = 60
    max_chunks_per_source: int = 3
    lexical_coverage_threshold: float = 0.61
    semantic_score_threshold: float = 0.45
    semantic_coverage_threshold: float = 0.2

    @classmethod
    def from_env(cls, data_paths=None):
        paths = data_paths or get_data_paths()
        rag_dir = Path(paths.rag_dir).resolve()
        base_url = (
            os.environ.get(
                "BUSHFIRE_RAG_EMBED_BASE_URL",
                "http://127.0.0.1:11434",
            )
            .strip()
            .rstrip("/")
        )
        if base_url.endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        _loopback_url(base_url)
        model = os.environ.get("BUSHFIRE_RAG_EMBED_MODEL", "embeddinggemma").strip()
        if not model or any(char.isspace() for char in model):
            raise RagError("rag_config_invalid", "BUSHFIRE_RAG_EMBED_MODEL must be one model name.")
        return cls(
            rag_dir=rag_dir,
            sources_path=Path(paths.rag_sources).resolve(),
            raw_dir=Path(paths.rag_raw_dir).resolve(),
            index_dir=Path(paths.rag_index_dir).resolve(),
            embedding_base_url=base_url,
            embedding_model=model,
            embedding_timeout_seconds=_positive_int("BUSHFIRE_RAG_EMBED_TIMEOUT_SECONDS", 60),
            embedding_batch_size=_positive_int("BUSHFIRE_RAG_EMBED_BATCH_SIZE", 16),
            top_k=_positive_int("BUSHFIRE_RAG_TOP_K", 8),
            score_threshold=_score("BUSHFIRE_RAG_SCORE_THRESHOLD", 0.35),
            enabled=_boolean("BUSHFIRE_RAG_ENABLED", True),
            candidate_multiplier=_positive_int("BUSHFIRE_RAG_CANDIDATE_MULTIPLIER", 4),
            dense_weight=_unit_interval("BUSHFIRE_RAG_DENSE_WEIGHT", 0.65),
            rrf_k=_positive_int("BUSHFIRE_RAG_RRF_K", 60),
            max_chunks_per_source=_positive_int("BUSHFIRE_RAG_MAX_CHUNKS_PER_SOURCE", 3),
            lexical_coverage_threshold=_unit_interval(
                "BUSHFIRE_RAG_LEXICAL_COVERAGE_THRESHOLD",
                0.61,
            ),
            semantic_score_threshold=_unit_interval(
                "BUSHFIRE_RAG_SEMANTIC_SCORE_THRESHOLD",
                0.45,
            ),
            semantic_coverage_threshold=_unit_interval(
                "BUSHFIRE_RAG_SEMANTIC_COVERAGE_THRESHOLD",
                0.2,
            ),
        )
