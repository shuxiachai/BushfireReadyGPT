"""Writable runtime locations, separate from the immutable application bundle."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def runtime_path(name="", *, project_root=None):
    """Resolve a runtime child while preserving the local chat_history default."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    configured = os.environ.get("BUSHFIRE_RUNTIME_DIR", "").strip()
    directory = Path(configured).expanduser() if configured else root / "chat_history"
    if not directory.is_absolute():
        directory = root / directory
    directory = directory.resolve()
    child = (directory / name).resolve()
    if not child.is_relative_to(directory):
        raise ValueError("Runtime paths must remain inside BUSHFIRE_RUNTIME_DIR.")
    return child
