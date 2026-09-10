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
        seed = seed_dir or os.environ.get("BUSHFIRE_RAG_SEED_DIR", "/opt/bushfire/seed/rag")
        rag_dir = install_rag_seed(seed)
        os.environ["BUSHFIRE_RAG_DIR"] = str(rag_dir)
        os.environ["BUSHFIRE_RAG_INDEX_DIR"] = str(rag_dir / "index")
        os.environ["BUSHFIRE_RAG_RAW_DIR"] = str(rag_dir / "raw")
        os.environ["BUSHFIRE_RAG_SOURCES_PATH"] = str(paths.rag_sources)
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
