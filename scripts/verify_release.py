"""Verify the committed v0.5.0 release evidence without network or model access."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation_artifacts import (  # noqa: E402
    ArtifactValidationError,
    sha256_file,
    validate_rag_evaluation_artifact,
    validate_report_evaluation_artifact,
)
from scripts.verify_sample_exports import verify_sample_package  # noqa: E402
from src.report_generation_quality import quality_policy_metadata  # noqa: E402

RELEASE_VERSION = "0.5.0"
RAG_QUESTIONS_PATH = Path("data_australia/rag/evaluation.json")
REPORT_SCENARIOS_PATH = Path("data_australia/rag/report_evaluation.json")
RAG_ARTIFACT_PATH = Path("docs/benchmarks/rag-retrieval-v0.5.0.json")
REPORT_ARTIFACT_PATH = Path("docs/benchmarks/report-generation-v0.5.0.json")
SAMPLE_DIRECTORY = Path("examples/v0.5.0")
SAMPLE_PACKAGE_PATH = SAMPLE_DIRECTORY / "cairns-council-pilot-package.zip"
_INDEX_IDENTITY_FIELDS = (
    "schema",
    "manifest_sha256",
    "catalog_sha256",
    "corpus_sha256",
    "documents_sha256",
    "embedding_dimension",
    "source_count",
    "chunk_count",
)


class ReleaseVerificationError(ValueError):
    """Raised when committed release evidence is absent, stale or inconsistent."""


@dataclass(frozen=True)
class ReleasePaths:
    """All paths needed by the offline release verifier."""

    pyproject: Path
    rag_questions: Path
    report_scenarios: Path
    rag_artifact: Path
    report_artifact: Path
    sample_package: Path
    sample_directory: Path

    @classmethod
    def for_project(cls, project_root: Path) -> ReleasePaths:
        root = Path(project_root).resolve()
        return cls(
            pyproject=root / "pyproject.toml",
            rag_questions=root / RAG_QUESTIONS_PATH,
            report_scenarios=root / REPORT_SCENARIOS_PATH,
            rag_artifact=root / RAG_ARTIFACT_PATH,
            report_artifact=root / REPORT_ARTIFACT_PATH,
            sample_package=root / SAMPLE_PACKAGE_PATH,
            sample_directory=root / SAMPLE_DIRECTORY,
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseVerificationError(message)


def _load_json(path: Path, label: str) -> dict:
    _require(path.is_file(), f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseVerificationError(f"{label} is unreadable: {path}") from error
    _require(isinstance(payload, dict), f"{label} must be a JSON object: {path}")
    return payload


def _project_version(pyproject_path: Path) -> str:
    _require(pyproject_path.is_file(), f"Project metadata is missing: {pyproject_path}")
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ReleaseVerificationError(f"Project metadata is unreadable: {pyproject_path}") from error
    version = (payload.get("project") or {}).get("version")
    _require(isinstance(version, str) and bool(version), "pyproject.toml does not declare project.version")
    return version


def _verify_dataset_binding(
    run: dict,
    *,
    source_path: Path,
    relative_path: Path,
    file_field: str,
    sha_field: str,
    hash_basis_field: str | None,
    schema_field: str,
) -> None:
    source = _load_json(source_path, f"Release source dataset {relative_path.as_posix()}")
    _require(
        run.get(file_field) == relative_path.as_posix(), f"Release artifact is not bound to {relative_path.as_posix()}"
    )
    _require(run.get(sha_field) == sha256_file(source_path), f"Release artifact uses a stale {relative_path.name} SHA")
    if hash_basis_field is not None:
        _require(
            run.get(hash_basis_field) == "exact_file_bytes", "Release dataset hash is not bound to exact file bytes"
        )
    _require(
        run.get(schema_field) == source.get("schema_version"),
        f"Release artifact uses a stale {relative_path.name} schema version",
    )


def _verify_release_gate(payload: dict, label: str) -> None:
    gate = payload.get("release_gate")
    _require(isinstance(gate, dict), f"{label} release gate is missing")
    _require(gate.get("active") is True, f"{label} release gate is inactive")
    _require(gate.get("passed") is True, f"{label} release gate did not pass")
    _require(payload.get("passed") is True, f"{label} evaluation did not pass")


def _verify_shared_provenance(rag_payload: dict, report_payload: dict) -> str:
    rag_run = rag_payload["run"]
    report_run = report_payload["run"]
    rag_commit = (rag_run.get("git") or {}).get("commit")
    report_commit = (report_run.get("git") or {}).get("commit")
    _require(rag_commit == report_commit, "RAG and report release evidence came from different Git commits")
    rag_index = rag_run.get("rag_index") or {}
    report_index = report_run.get("rag_index") or {}
    for field in _INDEX_IDENTITY_FIELDS:
        _require(
            rag_index.get(field) == report_index.get(field),
            f"RAG and report release evidence use different RAG index {field}",
        )
    return str(rag_commit)


def _verify_sample_runtime(sample: dict, rag_payload: dict, report_payload: dict) -> None:
    release_index = (rag_payload["run"].get("rag_index") or {}).get("manifest_sha256")
    _require(
        sample.get("rag_index_manifest_sha256") == release_index,
        "Showcase package uses a different RAG index from the release benchmarks",
    )
    _require(
        sample.get("model_endpoint_boundary") == "local_loopback",
        "Showcase package was not generated through a local loopback model endpoint",
    )
    report_model = report_payload["run"].get("model") or {}
    _require(
        sample.get("model_provider") == "ollama" == report_model.get("provider"),
        "Showcase and report benchmark must both use Ollama",
    )
    _require(
        sample.get("model_name") == report_model.get("name"),
        "Showcase package and report benchmark use different model names",
    )


def verify_release(
    project_root: Path = PROJECT_ROOT,
    *,
    paths: ReleasePaths | None = None,
) -> dict:
    """Validate the complete committed release evidence set offline."""

    root = Path(project_root).resolve()
    release_paths = paths or ReleasePaths.for_project(root)
    version = _project_version(release_paths.pyproject)
    _require(version == RELEASE_VERSION, f"Expected project version {RELEASE_VERSION}, found {version}")

    rag_payload = _load_json(release_paths.rag_artifact, "RAG release artifact")
    report_payload = _load_json(release_paths.report_artifact, "Report release artifact")
    try:
        validate_rag_evaluation_artifact(rag_payload)
        validate_report_evaluation_artifact(report_payload)
    except ArtifactValidationError as error:
        raise ReleaseVerificationError(f"Release artifact contract failed: {error}") from error

    _verify_release_gate(rag_payload, "RAG")
    _verify_release_gate(report_payload, "Report")
    _verify_dataset_binding(
        rag_payload["run"],
        source_path=release_paths.rag_questions,
        relative_path=RAG_QUESTIONS_PATH,
        file_field="questions_file",
        sha_field="questions_sha256",
        hash_basis_field="questions_hash_basis",
        schema_field="questions_schema_version",
    )
    _verify_dataset_binding(
        report_payload["run"],
        source_path=release_paths.report_scenarios,
        relative_path=REPORT_SCENARIOS_PATH,
        file_field="scenario_file",
        sha_field="scenario_file_sha256",
        hash_basis_field=None,
        schema_field="scenario_schema_version",
    )

    current_policy = quality_policy_metadata()
    recorded_policy = report_payload["run"].get("quality_policy")
    _require(recorded_policy == current_policy, "Report release artifact is not bound to the current quality policy")
    commit = _verify_shared_provenance(rag_payload, report_payload)

    try:
        sample = verify_sample_package(
            release_paths.sample_package,
            standalone_dir=release_paths.sample_directory,
            require_current_policy=True,
        )
    except ValueError as error:
        raise ReleaseVerificationError(f"Current showcase package failed verification: {error}") from error
    _require(sample.get("current_policy") is True, "Showcase package is not bound to the current quality policy")
    _require(sample.get("governed_gate_passed") is True, "Showcase package did not pass the governed report gate")
    _require(sample.get("quality_policy_version") == current_policy["version"], "Showcase policy version is stale")
    _require(
        sample.get("quality_policy_fingerprint") == current_policy["fingerprint"],
        "Showcase policy fingerprint is stale",
    )
    _verify_sample_runtime(sample, rag_payload, report_payload)

    return {
        "release_version": version,
        "verified_offline": True,
        "source_commit": commit,
        "quality_policy_version": current_policy["version"],
        "quality_policy_fingerprint": current_policy["fingerprint"],
        "rag_release_gate_passed": True,
        "report_release_gate_passed": True,
        "sample": sample,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    try:
        result = verify_release(args.project_root)
    except ReleaseVerificationError as error:
        parser.exit(1, f"Release verification failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
