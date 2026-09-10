"""Prepare, but never upload, a private Railway context from committed Git blobs.

Uncommitted and ignored workstation files are never read. Commit the intended
application changes first; the only non-Git input is a validated corpus bundle.
Subprocess use is limited to fixed Git read-only commands, without a shell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.corpus_bundle import install_corpus_bundle, validate_corpus_bundle  # noqa: E402

CONTEXT_MANIFEST = "private-context-manifest.json"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CONTEXT_BYTES = 256 * 1024 * 1024
MAX_FILE_COUNT = 10000
_ROOT_FILES = {
    "Dockerfile",
    "pyproject.toml",
    "poetry.lock",
    "LICENSE",
    "NOTICE",
    "UPSTREAM.md",
    "README.md",
    ".dockerignore",
    ".streamlit/config.toml",
}
_REQUIRED_FILES = {"Dockerfile", "pyproject.toml", "poetry.lock", ".dockerignore"}
_SECRET_PART = re.compile(r"(?:^|[._-])(?:secrets?|credentials?|private[-_]key)(?:[._-]|$)", re.IGNORECASE)
_RESERVED_NAME = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.IGNORECASE)


class ContextPreparationError(ValueError):
    """The deployment input or destination is unsafe or incomplete."""


def _git(repo, *arguments):
    executable = shutil.which("git")
    if executable is None:
        raise ContextPreparationError("Git is required to export the committed deployment snapshot.")
    # Only fixed commands and validated object IDs are used, without a shell.
    result = subprocess.run(  # nosec B603
        [executable, "-C", str(repo), *arguments],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise ContextPreparationError("Git could not read the committed deployment snapshot.")
    return result.stdout


def _without_links(path):
    candidate = Path(os.path.abspath(path))
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ContextPreparationError("Deployment paths cannot contain symbolic links or junctions.")
    return candidate


def _portable_path(value):
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(
            part in {".", ".."}
            or part.endswith((".", " "))
            or _RESERVED_NAME.fullmatch(part)
            or any(ord(char) < 32 for char in part)
            for part in path.parts
        )
    ):
        raise ContextPreparationError("A committed deployment path is not portable or safe.")
    return path


def _allowlisted(path):
    value = path.as_posix()
    if value in _ROOT_FILES:
        return True
    if path.parts[0] in {"src", "scripts", "examples"}:
        return True
    if path.parts[0] == "docs":
        return path.suffix.lower() != ".webm"
    if path.parts[0] != "data_australia":
        return False
    if value.startswith("data_australia/raw/"):
        return False
    if value.startswith("data_australia/rag/"):
        return bool(
            re.fullmatch(
                r"data_australia/rag/(?:sources\.yml|evaluation\.json|report_(?:evaluation|red_team)[^/]*\.json)",
                value,
            )
        )
    return value not in {
        "data_australia/processed/sa2_boundaries_all.geojson",
        "data_australia/processed/sa2_profiles_all.csv",
        "data_australia/processed/sa2_map_bundle.json",
    } and not value.startswith("data_australia/processed/sa2_boundaries_by_state/")


def _validate_export_path(path):
    for part in path.parts:
        folded = part.casefold()
        if (
            folded.startswith(".env")
            or _SECRET_PART.search(part)
            or folded.startswith(("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"))
            or Path(part).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".kdbx"}
            or (part.startswith(".") and path.as_posix() not in _ROOT_FILES)
        ):
            raise ContextPreparationError("A secret-like or hidden path exists inside the committed allowlist.")
    if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
        raise ContextPreparationError("A generated Python cache exists inside the committed allowlist.")


def _snapshot_entries(repo, commit):
    entries = []
    seen = set()
    for record in _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        header, encoded_path = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split()
        path = _portable_path(encoded_path.decode("utf-8"))
        if not _allowlisted(path):
            continue
        _validate_export_path(path)
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ContextPreparationError("Committed deployment files must be regular files, not links or submodules.")
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            raise ContextPreparationError("A committed deployment object has an invalid identity.")
        folded = path.as_posix().casefold()
        if folded in seen:
            raise ContextPreparationError("Committed deployment paths collide on case-insensitive filesystems.")
        seen.add(folded)
        entries.append((path.as_posix(), object_id, mode))
    if len(entries) > MAX_FILE_COUNT:
        raise ContextPreparationError("The committed context contains too many files.")
    if not _REQUIRED_FILES.issubset({entry[0] for entry in entries}):
        raise ContextPreparationError(
            "Commit Dockerfile, .dockerignore and dependency files before preparing deployment."
        )
    return entries


def _target_path(repo, corpus, output):
    target = _without_links(output)
    if target.exists():
        raise ContextPreparationError("The output already exists; choose a new directory. Nothing was overwritten.")
    if target == repo or repo.is_relative_to(target):
        raise ContextPreparationError("The output cannot be the repository or one of its ancestors.")
    if target.is_relative_to(repo) and target.relative_to(repo).parts[0] != "output":
        raise ContextPreparationError(
            "An in-repository context must be created under output/, not source or metadata directories."
        )
    if target == corpus or target.is_relative_to(corpus) or corpus.is_relative_to(target):
        raise ContextPreparationError("The deployment output and input corpus must be separate directories.")
    return target


def _export_blobs(repo, entries, staged):
    records = []
    total = 0
    for relative, object_id, mode in entries:
        size = int(_git(repo, "cat-file", "-s", object_id).decode("ascii").strip())
        total += size
        if size > MAX_FILE_BYTES or total > MAX_CONTEXT_BYTES:
            raise ContextPreparationError("The committed deployment context exceeds its file or total size limit.")
        payload = _git(repo, "cat-file", "blob", object_id)
        if len(payload) != size:
            raise ContextPreparationError("A Git object changed size while being exported.")
        destination = staged / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        destination.chmod(0o755 if mode == "100755" else 0o644)
        records.append({"path": relative, "size_bytes": size, "sha256": hashlib.sha256(payload).hexdigest()})
    return records


def prepare_railway_context(corpus_dir, output_dir=None, *, repo_dir=ROOT):
    """Export committed allowlisted blobs plus a validated private corpus, locally."""
    repo = _without_links(repo_dir)
    actual_root = Path(_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if actual_root != repo.resolve():
        raise ContextPreparationError("repo_dir must identify the Git repository root.")
    corpus = _without_links(corpus_dir)
    target = _target_path(repo, corpus, output_dir or repo / "output" / "railway-private-context")
    manifest = validate_corpus_bundle(corpus)
    commit = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ContextPreparationError("The committed snapshot identity is invalid.")
    entries = _snapshot_entries(repo, commit)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".railway-context-", dir=target.parent) as temporary:
        staged = Path(temporary) / "context"
        staged.mkdir()
        records = _export_blobs(repo, entries, staged)
        install_corpus_bundle(corpus, staged / "deployment_corpus")
        installed = validate_corpus_bundle(staged / "deployment_corpus")
        if installed["manifest_sha256"] != manifest["manifest_sha256"]:
            raise ContextPreparationError("The input corpus changed during context preparation.")
        summary = {
            "schema": "bushfire-private-railway-context-v1",
            "commit": commit,
            "snapshot_mode": "committed_HEAD_blobs_only",
            "file_count": len(records) + manifest["source_count"] + 3,
            "application_file_count": len(records),
            "source_count": manifest["source_count"],
            "corpus_manifest_sha256": manifest["manifest_sha256"],
            "fixture_only": manifest["fixture_only"],
            "uploaded": False,
            "files": records,
        }
        (staged / CONTEXT_MANIFEST).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        # copytree creates the destination exclusively; it never replaces an
        # existing directory, even if another process created one during staging.
        shutil.copytree(staged, target)
    return {key: value for key, value in summary.items() if key != "files"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="Validated local private corpus bundle.")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "railway-private-context")
    args = parser.parse_args(argv)
    try:
        summary = prepare_railway_context(args.corpus, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Context preparation failed: {type(error).__name__}.", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
