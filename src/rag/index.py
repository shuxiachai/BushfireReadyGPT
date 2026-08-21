from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.data_artifacts import atomic_write_bytes, atomic_write_json, sha256_file
from src.rag.corpus import (
    chunk_catalog_sources,
    load_source_catalog,
    source_artifact_records,
)
from src.rag.errors import RagError

RAG_INDEX_SCHEMA = "bushfire-rag-index-v2"
RAG_CHUNKER_VERSION = "paragraph-word-window-v1"


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_with_hash(payload):
    result = dict(payload)
    result["manifest_sha256"] = _canonical_sha256(payload)
    return result


def _serialise_documents(chunks):
    return b"".join(
        (
            json.dumps(
                chunk,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for chunk in chunks
    )


def _safe_index_target(settings):
    target = settings.index_dir.resolve()
    try:
        target.relative_to(settings.rag_dir.resolve())
    except ValueError as error:
        raise RagError(
            "rag_index_unsafe", "The RAG index directory must stay inside the configured RAG directory."
        ) from error
    if target == settings.rag_dir.resolve():
        raise RagError("rag_index_unsafe", "The RAG index cannot replace the RAG data root.")
    return target


@contextmanager
def _index_lock(settings, timeout_seconds=10):
    target = _safe_index_target(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.lock"
    deadline = time.monotonic() + timeout_seconds
    descriptor = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 60 * 60
            except OSError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise RagError("rag_index_locked", "Timed out waiting for the RAG index lock.") from error
            time.sleep(0.05)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _recover_index_publish(target):
    backup = target.parent / f".{target.name}.backup"
    if backup.exists() and not target.exists():
        os.replace(backup, target)
    elif backup.exists() and target.exists():
        shutil.rmtree(backup)
    for staging in target.parent.glob(f".{target.name}.*.stage"):
        if staging.is_dir():
            shutil.rmtree(staging)


def _publish_index(staging, target):
    backup = target.parent / f".{target.name}.backup"
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except BaseException:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_rag_index(settings, embedder, *, max_words=420, overlap_words=60):
    """Build a complete Qdrant local index in staging, then publish it atomically."""

    target = _safe_index_target(settings)
    catalog = load_source_catalog(settings.sources_path, rag_dir=settings.rag_dir)
    chunks = chunk_catalog_sources(
        catalog,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    vectors = embedder.embed([chunk["text"] for chunk in chunks])
    if len(vectors) != len(chunks) or not vectors:
        raise RagError("rag_embedding_invalid", "The embedding result does not match the RAG chunks.")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise RagError("rag_embedding_invalid", "RAG embedding vectors have inconsistent dimensions.")
    dimension = dimensions.pop()

    try:
        from qdrant_client import QdrantClient, models
    except ImportError as error:
        raise RagError("rag_dependency_missing", "qdrant-client is not installed.") from error

    with _index_lock(settings):
        _recover_index_publish(target)
        staging = target.parent / f".{target.name}.{uuid4().hex}.stage"
        staging.mkdir(parents=True)
        client = None
        try:
            client = QdrantClient(path=str(staging / "qdrant"))
            client.create_collection(
                collection_name=settings.collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            for start in range(0, len(chunks), 64):
                batch_chunks = chunks[start : start + 64]
                batch_vectors = vectors[start : start + 64]
                points = [
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, chunk["chunk_id"])),
                        vector=vector,
                        payload=chunk,
                    )
                    for chunk, vector in zip(batch_chunks, batch_vectors)
                ]
                client.upsert(
                    collection_name=settings.collection_name,
                    points=points,
                    wait=True,
                )
            client.close()
            client = None
            source_records = source_artifact_records(catalog, rag_dir=settings.rag_dir)
            documents_path = staging / "documents.jsonl"
            atomic_write_bytes(documents_path, _serialise_documents(chunks))
            manifest = _manifest_with_hash(
                {
                    "schema": RAG_INDEX_SCHEMA,
                    "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "collection_name": settings.collection_name,
                    "embedding_model": settings.embedding_model,
                    "embedding_dimension": dimension,
                    "chunker": {
                        "version": RAG_CHUNKER_VERSION,
                        "max_words": max_words,
                        "overlap_words": overlap_words,
                    },
                    "catalog_sha256": sha256_file(settings.sources_path),
                    "source_count": len(source_records),
                    "chunk_count": len(chunks),
                    "corpus_sha256": _canonical_sha256(
                        [
                            {
                                "chunk_id": chunk["chunk_id"],
                                "chunk_sha256": chunk["chunk_sha256"],
                            }
                            for chunk in chunks
                        ]
                    ),
                    "documents_artifact": {
                        "path": "documents.jsonl",
                        "size_bytes": documents_path.stat().st_size,
                        "sha256": sha256_file(documents_path),
                    },
                    "source_artifacts": source_records,
                }
            )
            atomic_write_json(staging / "manifest.json", manifest)
            _publish_index(staging, target)
        finally:
            if client is not None:
                client.close()
            if staging.exists():
                shutil.rmtree(staging)
    return manifest


def load_and_validate_index(settings):
    target = _safe_index_target(settings)
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        raise RagError("rag_not_built", "The optional RAG index has not been built.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RagError("rag_index_invalid", "The RAG index manifest is unreadable or invalid.") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != RAG_INDEX_SCHEMA:
        raise RagError("rag_index_invalid", "The RAG index manifest schema is invalid.")
    supplied_hash = manifest.get("manifest_sha256")
    hash_input = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if supplied_hash != _canonical_sha256(hash_input):
        raise RagError("rag_index_invalid", "The RAG index manifest hash does not match.")
    if manifest.get("embedding_model") != settings.embedding_model:
        raise RagError("rag_index_stale", "The RAG index was built with a different embedding model.")
    if manifest.get("collection_name") != settings.collection_name:
        raise RagError("rag_index_invalid", "The RAG index collection name does not match configuration.")
    if not (target / "qdrant").is_dir():
        raise RagError("rag_index_invalid", "The Qdrant local index directory is missing.")
    documents_artifact = manifest.get("documents_artifact")
    documents_path = target / "documents.jsonl"
    if (
        not isinstance(documents_artifact, dict)
        or documents_artifact.get("path") != "documents.jsonl"
        or isinstance(documents_artifact.get("size_bytes"), bool)
        or not isinstance(documents_artifact.get("size_bytes"), int)
        or documents_artifact["size_bytes"] < 1
        or not isinstance(documents_artifact.get("sha256"), str)
        or len(documents_artifact["sha256"]) != 64
        or not documents_path.is_file()
        or documents_path.stat().st_size != documents_artifact["size_bytes"]
        or sha256_file(documents_path) != documents_artifact["sha256"]
    ):
        raise RagError("rag_index_invalid", "The RAG document snapshot failed integrity validation.")
    if not settings.sources_path.is_file() or manifest.get("catalog_sha256") != sha256_file(settings.sources_path):
        raise RagError("rag_index_stale", "The RAG source catalog changed after the index was built.")
    catalog = load_source_catalog(settings.sources_path, rag_dir=settings.rag_dir)
    current_sources = source_artifact_records(catalog, rag_dir=settings.rag_dir)
    if current_sources != manifest.get("source_artifacts"):
        raise RagError("rag_index_stale", "A RAG source file changed after the index was built.")
    if (
        isinstance(manifest.get("embedding_dimension"), bool)
        or not isinstance(manifest.get("embedding_dimension"), int)
        or manifest["embedding_dimension"] < 1
        or isinstance(manifest.get("chunk_count"), bool)
        or not isinstance(manifest.get("chunk_count"), int)
        or manifest["chunk_count"] < 1
    ):
        raise RagError("rag_index_invalid", "The RAG index counts or dimensions are invalid.")
    return manifest


def load_index_documents(settings, manifest=None):
    manifest = manifest or load_and_validate_index(settings)
    path = _safe_index_target(settings) / manifest["documents_artifact"]["path"]
    documents = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    documents.append(json.loads(line))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RagError("rag_index_invalid", "The RAG document snapshot is unreadable.") from error
    if len(documents) != manifest["chunk_count"]:
        raise RagError("rag_index_invalid", "The RAG document count does not match the manifest.")
    source_ids = {row["source_id"] for row in manifest["source_artifacts"]}
    chunk_ids = set()
    for document in documents:
        if not isinstance(document, dict):
            raise RagError("rag_index_invalid", "The RAG document snapshot contains an invalid row.")
        chunk_id = document.get("chunk_id")
        text = document.get("text")
        content_hash = document.get("chunk_sha256")
        source_id = document.get("source_id")
        if (
            not isinstance(chunk_id, str)
            or chunk_id in chunk_ids
            or not isinstance(text, str)
            or not isinstance(content_hash, str)
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != content_hash
            or source_id not in source_ids
        ):
            raise RagError("rag_index_invalid", "A RAG document failed its logical integrity check.")
        identity = f"{source_id}:{document.get('page') or 0}:{document.get('chunk_number')}:{content_hash}"
        if hashlib.sha256(identity.encode("utf-8")).hexdigest() != chunk_id:
            raise RagError("rag_index_invalid", "A RAG document identity does not match its content.")
        chunk_ids.add(chunk_id)
    corpus_hash = _canonical_sha256(
        [
            {
                "chunk_id": document["chunk_id"],
                "chunk_sha256": document["chunk_sha256"],
            }
            for document in documents
        ]
    )
    if corpus_hash != manifest["corpus_sha256"]:
        raise RagError("rag_index_invalid", "The RAG document corpus does not match the manifest.")
    return documents


def index_snapshot(settings):
    manifest = load_and_validate_index(settings)
    return {
        "manifest_sha256": manifest["manifest_sha256"],
        "catalog_sha256": manifest["catalog_sha256"],
        "documents_sha256": manifest["documents_artifact"]["sha256"],
        "source_artifacts": manifest["source_artifacts"],
    }
