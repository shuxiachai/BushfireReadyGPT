from __future__ import annotations

import hashlib
import json
import math
import re
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
OLLAMA_IDENTITY_ENCODING = "ollama-api-embed-v1"
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


def observe_embedding_identity(settings, embedder=None):
    """Read a fresh provider identity; injected clients implement the same contract."""
    client = embedder or create_embedding_client(settings)
    identity_method = getattr(client, "identity", None)
    if not callable(identity_method):
        raise RagError("rag_embedding_invalid", "The embedding client must provide a verifiable model identity.")
    identity = identity_method()
    if settings.embedding_provider == "ollama":
        validate_ollama_identity(identity, model=settings.embedding_model)
    return identity


def validate_ollama_identity(identity, *, model, dimension=None):
    """Validate metadata shape without making network calls or inventing a digest."""
    keys = {"provider", "model", "resolved_model", "digest", "encoding"}
    if dimension is not None:
        keys.add("dimension")
    if (
        not isinstance(identity, dict)
        or set(identity) != keys
        or identity.get("provider") != "ollama"
        or identity.get("model") != model
        or identity.get("resolved_model") != _ollama_model_tag(model)
        or identity.get("encoding") != OLLAMA_IDENTITY_ENCODING
        or not isinstance(identity.get("digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", identity["digest"]) is None
        or dimension is not None
        and (
            type(dimension) is not int
            or dimension < 1
            or type(identity.get("dimension")) is not int
            or identity["dimension"] != dimension
        )
    ):
        raise RagError("rag_embedding_invalid", "The Ollama embedding model identity is missing or invalid.")


def embed_with_identity(settings, embedder, texts, identity):
    """Bind Ollama's batch observations to the caller's build/index identity."""
    if settings.embedding_provider == "ollama":
        expected = {key: value for key, value in identity.items() if key != "dimension"}
        validate_ollama_identity(expected, model=settings.embedding_model)
        return embedder.embed(texts, expected_identity=expected)
    return embedder.embed(texts)


def validate_embedding_identity(settings, manifest, embedder=None):
    """Compare a fresh provider identity with the model bound into an index."""
    provider = manifest.get("embedding_provider", "ollama")
    if provider != settings.embedding_provider:
        raise RagError("rag_index_stale", "The RAG index was built with a different embedding provider.")
    if provider == "ollama":
        expected = manifest.get("embedding_identity")
        if expected is None:
            raise RagError(
                "rag_index_migration_required",
                "This legacy Ollama index has no build-time model digest. Preserve it as historical evidence, "
                "build a new index with --new-index-dir, then explicitly select BUSHFIRE_RAG_INDEX_DIR.",
            )
        validate_ollama_identity(
            expected, model=settings.embedding_model, dimension=manifest.get("embedding_dimension")
        )
        actual = observe_embedding_identity(settings, embedder)
        if actual != {key: value for key, value in expected.items() if key != "dimension"}:
            raise RagError("rag_index_stale", "The Ollama embedding model digest changed; rebuild the RAG index.")
        return
    identity = observe_embedding_identity(settings, embedder)
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

    def identity(self):
        """Observe the current local tag digest; do not cache mutable model tags.

        Ollama exposes a digest via /api/tags, not /api/embed. Boundary checks
        detect observed drift, not an unobserved A-to-B-to-A change inside HTTP.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/tags", timeout=(5, self.timeout_seconds), allow_redirects=False
            )
            if 300 <= response.status_code < 400:
                raise RagError("rag_embedding_unavailable", "The local model identity endpoint redirected.")
            response.raise_for_status()
            payload = response.json()
        except RagError:
            raise
        except (requests.RequestException, ValueError) as error:
            raise RagError("rag_embedding_unavailable", "The local Ollama model identity is unavailable.") from error
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise RagError("rag_embedding_invalid", "Ollama returned an invalid model identity response.")
        tag = _ollama_model_tag(self.model)
        digests = set()
        for item in models:
            if not isinstance(item, dict):
                continue
            names = [item.get("name"), item.get("model")]
            if not any(isinstance(name, str) and _ollama_model_tag(name) == tag for name in names):
                continue
            digest = item.get("digest")
            if not isinstance(digest, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-fA-F]{64}", digest):
                raise RagError("rag_embedding_invalid", "Ollama returned an invalid model digest.")
            digests.add(digest.lower().removeprefix("sha256:"))
        if len(digests) != 1:
            raise RagError(
                "rag_embedding_unavailable", "The configured Ollama embedding model has no unambiguous digest."
            )
        return {
            "provider": "ollama",
            "model": self.model,
            "resolved_model": tag,
            "digest": digests.pop(),
            "encoding": OLLAMA_IDENTITY_ENCODING,
        }

    def embed(self, texts, *, expected_identity=None):
        values = [str(text or "").strip() for text in texts]
        if not values or any(not value for value in values):
            raise RagError("rag_embedding_invalid", "Embedding input must contain non-empty text.")
        result = []
        identity = self.identity()
        if expected_identity is not None and identity != expected_identity:
            raise RagError(
                "rag_embedding_changed", "The Ollama embedding model no longer matches the bound index identity."
            )
        for index in range(0, len(values), self.batch_size):
            batch = values[index : index + self.batch_size]
            if index and self.identity() != identity:
                raise RagError("rag_embedding_changed", "The Ollama embedding model changed between batches.")
            try:
                response = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=(5, self.timeout_seconds),
                    allow_redirects=False,
                )
                if 300 <= response.status_code < 400:
                    raise RagError(
                        "rag_embedding_unavailable", "The local embedding endpoint returned a forbidden redirect."
                    )
                response.raise_for_status()
                payload = response.json()
            except RagError:
                raise
            except (requests.RequestException, ValueError) as error:
                raise RagError(
                    "rag_embedding_unavailable",
                    f"The local Ollama embedding model '{self.model}' is unavailable.",
                ) from error
            embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
            response_model = payload.get("model") if isinstance(payload, dict) else None
            if not isinstance(response_model, str) or _ollama_model_tag(response_model) != identity["resolved_model"]:
                raise RagError("rag_embedding_invalid", "Ollama returned embeddings from an unexpected model.")
            if self.identity() != identity:
                raise RagError("rag_embedding_changed", "The Ollama embedding model changed during inference.")
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


def _ollama_model_tag(model):
    # A registry hostname may include a port; only the final path component has
    # a model tag. An omitted tag is Ollama's explicit latest alias.
    return model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
