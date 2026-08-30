"""Resolve versioned release paths without trusting user-controlled traversal."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_RELEASE_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_VERSIONED_REPORT_SCENARIO_MINIMUM = (0, 6, 0)


class ReleasePathError(ValueError):
    """Raised when release metadata or a repository-relative path is invalid."""


def validate_release_version(value: str) -> str:
    """Return a strict ``major.minor.patch`` release version."""

    if not isinstance(value, str) or _RELEASE_VERSION.fullmatch(value) is None:
        raise ReleasePathError("Release version must use numeric major.minor.patch format (for example, 0.6.0).")
    return value


def release_version_tuple(value: str) -> tuple[int, int, int]:
    """Return a validated release version as a comparable integer tuple."""

    return tuple(int(part) for part in validate_release_version(value).split("."))


def report_scenario_relative_path(release_version: str) -> Path:
    """Return the immutable product-scenario path used by one release."""

    version = validate_release_version(release_version)
    if release_version_tuple(version) >= _VERSIONED_REPORT_SCENARIO_MINIMUM:
        return Path("data_australia") / "rag" / f"report_evaluation-v{version}.json"
    return Path("data_australia") / "rag" / "report_evaluation.json"


def project_version(project_root: Path) -> str:
    """Read and validate ``project.version`` from a repository's pyproject file."""

    pyproject_path = Path(project_root).resolve() / "pyproject.toml"
    if not pyproject_path.is_file():
        raise ReleasePathError(f"Project metadata is missing: {pyproject_path}")
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ReleasePathError(f"Project metadata is unreadable: {pyproject_path}") from error
    version = (payload.get("project") or {}).get("version")
    if not isinstance(version, str):
        raise ReleasePathError("pyproject.toml does not declare project.version")
    return validate_release_version(version)


def resolve_release_version(project_root: Path, release_version: str | None = None) -> str:
    """Use an explicit release version, or fall back to project metadata."""

    return validate_release_version(release_version) if release_version is not None else project_version(project_root)


def repository_path(project_root: Path, candidate: Path | str, *, label: str) -> Path:
    """Resolve a path and require it to remain inside ``project_root``."""

    root = Path(project_root).resolve()
    raw_path = Path(candidate)
    resolved = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ReleasePathError(f"{label} must stay inside the project root: {resolved}") from error
    return resolved


def resolve_release_directory(
    project_root: Path,
    *,
    release_version: str | None = None,
    release_dir: Path | str | None = None,
) -> tuple[str, Path]:
    """Resolve the release version and its repository-contained sample directory."""

    version = resolve_release_version(project_root, release_version)
    candidate = release_dir if release_dir is not None else Path("examples") / f"v{version}"
    directory = repository_path(project_root, candidate, label="Release directory")
    return version, directory
