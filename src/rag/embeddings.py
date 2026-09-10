from __future__ import annotations

import hashlib
import json
import math
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import requests

from src.data_artifacts import atomic_write_json, sha256_file
from src.rag.errors import RagError

FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
FASTEMBED_REPOSITORY = "Qdrant/bge-small-en-v1.5-onnx-Q"
FASTEMBED_REVISION = "52398278842ec682c6f32300af41344b1c0b0bb2"
FASTEMBED_DIMENSION = 384
_MODEL_FILES = (
    "config.json",
    "model_optimized.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
_MODEL_CLIENTS = {}
_MODEL_CLIENTS_LOCK = threading.Lock()


def _identity_digest(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _model_directory(settings):
    if settings.embedding_model != FASTEMBED_MODEL:
        raise RagError("rag_config_invalid", "The CPU embedding model is unsupported.")
    cache = settings.embedding_cache_dir or settings.rag_dir / "models"
    return Path(cache).resolve() / "bge-small-en-v1.5"


def _model_identity(directory):
    try:
        runtime = {name: version(name) for name in ("fastembed", "onnxruntime")}
        files = []
        for name in _MODEL_FILES:
            path = directory / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size < 1:
                raise OSError("A required embedding model file is missing or unsafe.")
            files.append({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    except (OSError, PackageNotFoundError) as error:
        raise RagError(
            "rag_embedding_model_invalid", "The prepared CPU embedding model files are missing or unreadable."
        ) from error
    identity = {
        "provider": "fastembed",
        "model": FASTEMBED_MODEL,
        "dimension": FASTEMBED_DIMENSION,
        "repository": FASTEMBED_REPOSITORY,
        "revision": FASTEMBED_REVISION,
        "encoding": "fastembed-raw-text-v1",
        "runtime": runtime,
        "files": files,
    }
    return {**identity, "digest": _identity_digest(identity)}


def prepare_embedding_model(settings):
    """Explicit build-time download; inference never invokes a download API."""
    if settings.embedding_provider != "fastembed":
        raise RagError("rag_config_invalid", "Model preparation is only supported for the CPU embedding provider.")
    directory = _model_directory(settings)
    try:
        from huggingface_hub import hf_hub_download

        directory.mkdir(parents=True, exist_ok=True)
        for name in _MODEL_FILES:
            hf_hub_download(
                repo_id=FASTEMBED_REPOSITORY,
                revision=FASTEMBED_REVISION,
                filename=name,
                local_dir=str(directory),
                local_files_only=settings.embedding_local_files_only,
                token=False,
            )
        identity = _model_identity(directory)
        atomic_write_json(directory / "identity.json", identity)
        return identity
    except RagError:
        raise
    except Exception as error:  # Normalize provider-specific HTTP/download failures at this adapter boundary.
        raise RagError(
            "rag_embedding_unavailable",
            "CPU embedding model preparation failed; install fastembed and prepare the explicit model cache during build.",
        ) from error


def validate_embedding_identity(settings, manifest, embedder=None):
    """Validate current model bytes against the identity bound into a CPU index."""
    provider = manifest.get("embedding_provider", "ollama")
    if provider != settings.embedding_provider:
        raise RagError("rag_index_stale", "The RAG index was built with a different embedding provider.")
    if provider != "fastembed":
        return
    client = embedder or create_embedding_client(settings)
    identity = client.identity()
    if (
        identity != manifest.get("embedding_identity")
        or identity.get("dimension") != manifest.get("embedding_dimension")
        or identity.get("model") != manifest.get("embedding_model")
    ):
        raise RagError("rag_index_stale", "The RAG index does not match the prepared CPU embedding model files.")


class FastEmbedEmbeddingClient:
    """One lazy, CPU-only model per process with immutable, hashed model assets."""

    def __init__(self, settings):
        self.model = settings.embedding_model
        self.directory = _model_directory(settings)
        self.batch_size = settings.embedding_batch_size
        self.threads = settings.embedding_threads
        self._model = None
        self._identity = None
        self._file_state = None
        self._lock = threading.RLock()

    def identity(self):
        with self._lock:
            try:
                names = (*_MODEL_FILES, "identity.json")
                state = tuple(
                    (name, (stat := (self.directory / name).stat()).st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                    for name in names
                )
                if self._identity is not None and state == self._file_state:
                    return json.loads(json.dumps(self._identity))
                expected = json.loads((self.directory / "identity.json").read_text(encoding="utf-8"))
                actual = _model_identity(self.directory)
                if actual != expected or (self._identity is not None and actual != self._identity):
                    raise RagError(
                        "rag_embedding_model_invalid", "CPU embedding model files changed after preparation."
                    )
                self._identity, self._file_state = actual, state
                return json.loads(json.dumps(actual))
            except RagError:
                raise
            except (OSError, ValueError) as error:
                raise RagError(
                    "rag_embedding_model_invalid",
                    "CPU embedding model cache is missing or invalid; run explicit model preparation before startup.",
                ) from error

    def embed(self, texts):
        values = [str(text or "").strip() for text in texts]
        if not values or any(not value for value in values):
            raise RagError("rag_embedding_invalid", "Embedding input must contain non-empty text.")
        with self._lock:
            self.identity()
            try:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(
                        model_name=self.model,
                        cache_dir=str(self.directory.parent),
                        specific_model_path=str(self.directory),
                        local_files_only=True,
                        providers=["CPUExecutionProvider"],
                        threads=self.threads,
                    )
                vectors = [
                    vector.tolist() for vector in self._model.embed(values, batch_size=self.batch_size, parallel=None)
                ]
                self.identity()
            except RagError:
                raise
            except Exception as error:  # ONNX Runtime uses provider-specific exception classes.
                raise RagError(
                    "rag_embedding_unavailable", "The prepared CPU embedding model could not run."
                ) from error
        if len(vectors) != len(values) or any(
            len(vector) != FASTEMBED_DIMENSION
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in vector
            )
            for vector in vectors
        ):
            raise RagError("rag_embedding_invalid", "The CPU embedding model returned invalid vectors.")
        return vectors


def create_embedding_client(settings):
    """Shared build/query factory; CPU inference models are reused across UI reruns."""
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingClient(
            settings.embedding_base_url,
            settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            batch_size=settings.embedding_batch_size,
        )
    if settings.embedding_provider != "fastembed":
        raise RagError("rag_config_invalid", "The embedding provider is unsupported.")
    key = (
        str(_model_directory(settings)),
        settings.embedding_model,
        settings.embedding_threads,
        settings.embedding_batch_size,
    )
    with _MODEL_CLIENTS_LOCK:
        if key not in _MODEL_CLIENTS:
            _MODEL_CLIENTS[key] = FastEmbedEmbeddingClient(settings)
        return _MODEL_CLIENTS[key]


class OllamaEmbeddingClient:
    def __init__(self, base_url, model, *, timeout_seconds=60, batch_size=16):
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model)
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size

    def embed(self, texts):
        values = [str(text or "").strip() for text in texts]
        if not values or any(not value for value in values):
            raise RagError("rag_embedding_invalid", "Embedding input must contain non-empty text.")
        result = []
        for index in range(0, len(values), self.batch_size):
            batch = values[index : index + self.batch_size]
            try:
                response = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=(5, self.timeout_seconds),
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as error:
                raise RagError(
                    "rag_embedding_unavailable",
                    f"The local Ollama embedding model '{self.model}' is unavailable.",
                ) from error
            embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise RagError("rag_embedding_invalid", "Ollama returned an invalid embedding batch.")
            for vector in embeddings:
                if (
                    not isinstance(vector, list)
                    or not vector
                    or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in vector)
                    or any(not math.isfinite(float(item)) for item in vector)
                ):
                    raise RagError("rag_embedding_invalid", "Ollama returned an invalid embedding vector.")
                result.append([float(item) for item in vector])
        dimensions = {len(vector) for vector in result}
        if len(dimensions) != 1:
            raise RagError("rag_embedding_invalid", "Ollama returned inconsistent embedding dimensions.")
        return result
