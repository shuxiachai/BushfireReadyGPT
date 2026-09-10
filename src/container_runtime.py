"""Container startup checks and versioned RAG initialization on a persistent volume."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from src.data_artifacts import validate_data_manifest
from src.data_paths import get_data_paths
from src.runtime_paths import runtime_path


def server_port(value=None):
    raw = os.environ.get("PORT", "8501") if value is None else value
    try:
        port = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("PORT must be an integer between 1 and 65535.") from error
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535.")
    return port


def initialize_volume_permissions():
    """Railway mounts as root; initialize only the runtime root, then drop privileges."""
    directory = runtime_path()
    if directory in {Path("/"), Path("/app"), Path("/opt"), Path("/usr"), Path("/etc")}:
        raise ValueError("BUSHFIRE_RUNTIME_DIR must name a dedicated writable data directory.")
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and os.getuid() == 0:
        import pwd

        account = pwd.getpwnam("bushfire")
        os.chown(directory, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ["HOME"] = account.pw_dir


def _seed_version(seed):
    manifest_path = seed / "index" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest["manifest_sha256"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("The image does not contain a valid RAG seed manifest.") from error
    if not isinstance(version, str) or re.fullmatch(r"[0-9a-f]{64}", version) is None:
        raise ValueError("The image RAG seed identity is invalid.")
    return version


def install_rag_seed(seed_dir, *, target_root=None):
    """Copy a new immutable seed once; reuse or reject existing state without overwriting it."""
    seed = Path(seed_dir).resolve()
    version = _seed_version(seed)
    parent = Path(target_root).resolve() if target_root is not None else runtime_path("rag")
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / version
    if target.is_symlink():
        raise ValueError("The runtime RAG directory must not be a symbolic link.")
    if target.exists():
        if not target.is_dir():
            raise ValueError("The runtime RAG version must be a directory.")
        return target
    for source in seed.rglob("*"):
        if source.is_symlink():
            raise ValueError("The image RAG seed must contain regular files and directories only.")
    with tempfile.TemporaryDirectory(prefix=".seed-", dir=parent) as temporary:
        staged = Path(temporary) / "rag"
        staged.mkdir()
        for child in ("raw", "index"):
            shutil.copytree(seed / child, staged / child, ignore=shutil.ignore_patterns(".lock", "*.guard"))
        from src.rag.index import load_and_validate_index
        from src.rag.settings import RagSettings

        current = RagSettings.from_env()
        staged_settings = replace(current, rag_dir=staged, raw_dir=staged / "raw", index_dir=staged / "index")
        load_and_validate_index(staged_settings)
        try:
            staged.rename(target)
        except OSError:
            # Another initializer may have published the same version. Its contents
            # still undergo full index validation before the service starts.
            if not target.is_dir() or target.is_symlink():
                raise
    return target


def _corpus_identity(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("BUSHFIRE_RAG_CORPUS_SHA256 must be a lowercase canonical bundle manifest SHA-256.")
    return value


def _unlinked_corpus_path(path):
    candidate = Path(os.path.abspath(Path(path).expanduser()))
    if any(
        part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
        for part in (candidate, *candidate.parents)
    ):
        raise ValueError("Private corpus paths must not contain symbolic links or junctions.")
    return candidate


def _private_rag_parent(target_root):
    if target_root is not None:
        return _unlinked_corpus_path(target_root)
    configured = os.environ.get("BUSHFIRE_RUNTIME_DIR", "").strip()
    root = Path(configured).expanduser() if configured else runtime_path()
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    return _unlinked_corpus_path(root / "private-rag")


def _validate_private_bundle(path, expected, *, allow_index=False):
    from src.corpus_bundle import validate_corpus_bundle

    manifest = validate_corpus_bundle(path, allow_index=allow_index)
    if manifest["manifest_sha256"] != expected:
        raise ValueError("The private corpus does not match BUSHFIRE_RAG_CORPUS_SHA256.")
    if manifest["fixture_only"] and os.environ.get("BUSHFIRE_CONTAINER_SMOKE", "").strip().lower() != "true":
        raise ValueError("Synthetic test-only corpus requires BUSHFIRE_CONTAINER_SMOKE=true.")
    return manifest


def _private_rag_settings(path):
    from src.rag.settings import RagSettings

    current = RagSettings.from_env()
    if current.embedding_provider != "fastembed" or not current.embedding_local_files_only:
        raise ValueError("Private cloud RAG requires the prepared CPU embedding provider in offline-only mode.")
    if current.embedding_cache_dir is not None:
        _unlinked_corpus_path(current.embedding_cache_dir)
    return replace(
        current, rag_dir=path, sources_path=path / "sources.yml", raw_dir=path / "raw", index_dir=path / "index"
    )


def _validate_private_rag(path, expected):
    from src.rag.index import load_and_validate_index, load_index_documents
    from src.rag.service import RagService

    _unlinked_corpus_path(path)
    _validate_private_bundle(path, expected, allow_index=True)
    settings = _private_rag_settings(path)
    manifest = load_and_validate_index(settings)
    load_index_documents(settings, manifest)
    warmup = RagService(settings).retrieve("Bushfire preparedness planning", trusted_planning_scope=True)
    if warmup.get("status") not in {"ready", "no_match"}:
        raise ValueError("The private RAG index could not complete a verified retrieval at startup.")
    # Retrieval may open index lock files, but must not change the bound catalog or raw corpus.
    _validate_private_bundle(path, expected, allow_index=True)
    return manifest


def _publish_private_rag(staged, target):
    """Publish a directory atomically without replacing even an empty competing target."""
    _unlinked_corpus_path(target)
    if target.exists():
        raise ValueError("A private RAG version appeared during initialization; nothing was overwritten.")
    if sys.platform.startswith("linux"):
        import ctypes

        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise ValueError("This filesystem runtime cannot safely publish a new private RAG version.")
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        # AT_FDCWD and RENAME_NOREPLACE prevent os.rename's empty-directory overwrite on POSIX.
        if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, "The private RAG version could not be published without replacement.")
    elif os.name == "nt":
        staged.rename(target)
    else:
        raise ValueError("Atomic private corpus publication is currently supported on Linux and Windows.")


def install_private_rag_corpus(bundle_dir, expected_sha256, *, target_root=None):
    """Verify and build an immutable CPU index once, entirely from local private source bytes."""
    from src.corpus_bundle import CorpusBundleError, install_corpus_bundle
    from src.rag.errors import RagError
    from src.rag.index import build_rag_index, index_read_write_lock

    expected = _corpus_identity(expected_sha256)
    try:
        parent = _private_rag_parent(target_root)
        target = parent / expected
        _unlinked_corpus_path(target)
        existing = target.exists()
        current = _private_rag_settings(target)
        # Existing targets are validated first; the image may no longer carry a bundle on restart.
        if not existing:
            source = _unlinked_corpus_path(bundle_dir)
            if source == parent or source.is_relative_to(parent) or parent.is_relative_to(source):
                raise ValueError("The image corpus and persistent private RAG directory must be separate.")
            _validate_private_bundle(source, expected)
        parent.mkdir(parents=True, exist_ok=True)
        _unlinked_corpus_path(parent)
        lock_settings = replace(current, rag_dir=parent, index_dir=target)
        for suffix in (".lock", ".lock.guard"):
            _unlinked_corpus_path(parent / f".{expected}{suffix}")
        with index_read_write_lock(lock_settings, timeout_seconds=600):
            _unlinked_corpus_path(target)
            if target.exists():
                if not target.is_dir():
                    raise ValueError("The existing private RAG version must be a directory; nothing was overwritten.")
                _validate_private_rag(target, expected)
                return target
            if existing:
                raise ValueError(
                    "The existing private RAG version disappeared during initialization; no rebuild was attempted."
                )
            with tempfile.TemporaryDirectory(prefix=".corpus-", dir=parent) as temporary:
                staged = Path(temporary) / "rag"
                install_corpus_bundle(bundle_dir, staged)
                _validate_private_bundle(staged, expected)
                build_rag_index(_private_rag_settings(staged))
                _validate_private_rag(staged, expected)
                _publish_private_rag(staged, target)
            _validate_private_rag(target, expected)
        return target
    except (CorpusBundleError, RagError, OSError) as error:
        raise ValueError(
            "Private corpus initialization failed integrity, storage or CPU-model validation. "
            "Restore the expected bundle and matching prepared model; existing versions were not replaced."
        ) from error


def prepare_runtime(*, seed_dir=None):
    from src.deployment_access import is_cloud_deployment, validate_deployment_settings

    validate_deployment_settings()
    port = server_port()
    paths = get_data_paths()
    validate_data_manifest(paths.manifest, data_dir=paths.data_dir)
    directory = runtime_path()
    directory.mkdir(parents=True, exist_ok=True)
    # Confirm the non-root worker can actually persist audit/quota state on the mount.
    with tempfile.TemporaryFile(dir=directory) as probe:
        probe.write(b"ready")
        probe.flush()
    if is_cloud_deployment():
        if os.environ.get("BUSHFIRE_RAG_ENABLED", "true").strip().lower() != "true":
            raise ValueError("The cloud demo requires BUSHFIRE_RAG_ENABLED=true.")
        corpus_sha = os.environ.get("BUSHFIRE_RAG_CORPUS_SHA256")
        if corpus_sha is not None:
            bundle_dir = os.environ.get("BUSHFIRE_RAG_CORPUS_BUNDLE", "/opt/bushfire/corpus")
            rag_dir = install_private_rag_corpus(bundle_dir, corpus_sha)
        else:
            seed = seed_dir or os.environ.get("BUSHFIRE_RAG_SEED_DIR", "/opt/bushfire/seed/rag")
            try:
                rag_dir = install_rag_seed(seed)
            except ValueError as error:
                if seed_dir is None and "BUSHFIRE_RAG_SEED_DIR" not in os.environ:
                    raise ValueError(
                        "No verified RAG corpus is configured in this image. Include a private corpus bundle and set "
                        "BUSHFIRE_RAG_CORPUS_SHA256 to its canonical manifest identity before starting the cloud demo."
                    ) from error
                raise
        os.environ["BUSHFIRE_RAG_DIR"] = str(rag_dir)
        os.environ["BUSHFIRE_RAG_INDEX_DIR"] = str(rag_dir / "index")
        os.environ["BUSHFIRE_RAG_RAW_DIR"] = str(rag_dir / "raw")
        os.environ["BUSHFIRE_RAG_SOURCES_PATH"] = str(
            rag_dir / "sources.yml" if corpus_sha is not None else paths.rag_sources
        )
        from src.rag.index import load_and_validate_index
        from src.rag.service import RagService
        from src.rag.settings import RagSettings

        settings = RagSettings.from_env()
        if settings.embedding_provider != "fastembed":
            raise ValueError("The cloud demo requires the prepared local CPU embedding provider.")
        manifest = load_and_validate_index(settings)
        warmup = RagService(settings).retrieve("Bushfire preparedness planning", trusted_planning_scope=True)
        if warmup.get("status") not in {"ready", "no_match"}:
            raise ValueError("The image RAG index could not complete a verified retrieval at startup.")
        rag_summary = {"status": "ready", "manifest_sha256": manifest["manifest_sha256"]}
        if corpus_sha is not None:
            rag_summary["corpus_manifest_sha256"] = corpus_sha
    else:
        rag_summary = {"status": "local_configuration"}
    # Import only after safe deployment validation, so missing provider configuration
    # stops startup instead of producing a superficially healthy Streamlit server.
    from src.config import EXTERNAL_MODEL_ALLOWED, LLM_PROVIDER, MODEL_ENDPOINT_IS_LOCAL, model

    if is_cloud_deployment() and (MODEL_ENDPOINT_IS_LOCAL or not EXTERNAL_MODEL_ALLOWED):
        raise ValueError("Cloud report generation requires an allowed HTTPS external model provider.")
    return {"port": port, "provider": LLM_PROVIDER, "model": model, "rag": rag_summary}


def streamlit_command(port):
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/wildfireChat.py",
        "--server.address=0.0.0.0",
        f"--server.port={port}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
    ]
