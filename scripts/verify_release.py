"""Verify a committed release evidence set without network or model access."""

from __future__ import annotations

import argparse
import json
import sys
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
from scripts.release_paths import (  # noqa: E402
    ReleasePathError,
    project_version,
    release_version_tuple,
    report_scenario_relative_path,
    resolve_release_directory,
    validate_release_version,
)
from scripts.verify_sample_exports import verify_sample_package  # noqa: E402
from src.report_generation_quality import quality_policy_metadata  # noqa: E402

RAG_QUESTIONS_PATH = Path("data_australia/rag/evaluation.json")
REPORT_SCENARIOS_PATH = Path("data_australia/rag/report_evaluation.json")
RED_TEAM_MINIMUM_VERSION = (0, 6, 0)
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

    release_version: str
    pyproject: Path
    rag_questions: Path
    report_scenarios: Path
    red_team_scenarios: Path
    rag_artifact: Path
    report_artifact: Path
    red_team_artifact: Path
    sample_package: Path
    sample_directory: Path

    @classmethod
    def for_project(
        cls,
        project_root: Path,
        *,
        release_version: str | None = None,
        release_dir: Path | str | None = None,
    ) -> ReleasePaths:
        root = Path(project_root).resolve()
        version, sample_directory = resolve_release_directory(
            root,
            release_version=release_version,
            release_dir=release_dir,
        )
        report_scenarios_path = report_scenario_relative_path(version)
        return cls(
            release_version=version,
            pyproject=root / "pyproject.toml",
            rag_questions=root / RAG_QUESTIONS_PATH,
            report_scenarios=root / report_scenarios_path,
            red_team_scenarios=root / "data_australia" / "rag" / f"report_red_team-v{version}.json",
            rag_artifact=root / "docs" / "benchmarks" / f"rag-retrieval-v{version}.json",
            report_artifact=root / "docs" / "benchmarks" / f"report-generation-v{version}.json",
            red_team_artifact=root / "docs" / "benchmarks" / f"report-red-team-v{version}.json",
            sample_package=sample_directory / "cairns-council-pilot-package.zip",
            sample_directory=sample_directory,
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
    try:
        return project_version(pyproject_path.parent)
    except ReleasePathError as error:
        raise ReleaseVerificationError(str(error)) from error


def _verify_dataset_binding(
    run: dict,
    *,
    source_path: Path,
    relative_path: Path,
    file_field: str,
    sha_field: str,
    hash_basis_field: str | None,
    schema_field: str,
) -> dict:
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
    return source


def _verify_scenario_suite_binding(payload: dict, source: dict, *, label: str) -> None:
    """Bind artifact decisions to the exact source suite semantics, not only its byte hash."""

    run = payload.get("run") or {}
    selection = payload.get("selection") or {}
    scenarios = source.get("scenarios")
    _require(isinstance(scenarios, list) and scenarios, f"{label} source scenarios are missing")
    expected_ids = [str(scenario.get("id") or "") for scenario in scenarios if isinstance(scenario, dict)]
    _require(len(expected_ids) == len(scenarios) and all(expected_ids), f"{label} source scenario IDs are invalid")
    _require(
        selection.get("declared_scenario_ids") == expected_ids,
        f"{label} artifact scenario IDs do not match the bound source suite",
    )
    _require(
        payload.get("thresholds") == source.get("thresholds"),
        f"{label} artifact thresholds do not match the bound source suite",
    )
    source_kind = source.get("suite_kind")
    source_version = source.get("suite_version")
    _require(
        run.get("scenario_suite_kind") == source_kind,
        f"{label} artifact suite kind does not match the bound source suite",
    )
    _require(
        run.get("scenario_suite_version") == source_version,
        f"{label} artifact suite version does not match the bound source suite",
    )
    if source.get("schema_version") >= 3:
        expected_kinds = [
            {
                "id": scenario["id"],
                "kind": scenario.get("kind", "product_scenario"),
                "attack_surface": scenario.get("attack_surface"),
            }
            for scenario in scenarios
        ]
        _require(
            selection.get("declared_scenario_kinds") == expected_kinds,
            f"{label} artifact scenario kinds do not match the bound source suite",
        )


def _verify_rag_suite_binding(payload: dict, source: dict) -> None:
    questions = source.get("questions")
    _require(isinstance(questions, list) and questions, "RAG source questions are missing")
    question_ids = [str(question.get("id") or "") for question in questions if isinstance(question, dict)]
    _require(len(question_ids) == len(questions) and all(question_ids), "RAG source question IDs are invalid")
    source_thresholds = source.get("thresholds")
    source_profile_thresholds = source.get("profile_thresholds") or {}
    default_profiles = {"structured_planning", "free_text"}
    expected_profiles = {
        profile_name for question in questions for profile_name in question.get("evaluation_profiles", default_profiles)
    }
    profiles = payload.get("profiles") or {}
    _require(set(profiles) == expected_profiles, "RAG artifact profiles do not match the bound source suite")
    for profile_name, profile in profiles.items():
        expected_thresholds = dict(source_thresholds or {})
        expected_thresholds.update(source_profile_thresholds.get(profile_name, {}))
        expected_ids = [
            str(question["id"])
            for question in questions
            if profile_name in question.get("evaluation_profiles", default_profiles)
        ]
        _require(
            profile.get("thresholds") == expected_thresholds,
            f"RAG profile {profile_name} thresholds do not match the bound source suite",
        )
        _require(
            [row.get("id") for row in profile.get("rows") or []] == expected_ids,
            f"RAG profile {profile_name} question IDs do not match the bound source suite",
        )


def _verify_release_gate(payload: dict, label: str) -> None:
    gate = payload.get("release_gate")
    _require(isinstance(gate, dict), f"{label} release gate is missing")
    _require(gate.get("active") is True, f"{label} release gate is inactive")
    _require(gate.get("passed") is True, f"{label} release gate did not pass")
    _require(payload.get("passed") is True, f"{label} evaluation did not pass")


def _verify_diagnostic_gate(payload: dict, label: str) -> None:
    gate = payload.get("diagnostic_gate")
    release_gate = payload.get("release_gate")
    _require(isinstance(gate, dict), f"{label} diagnostic gate is missing")
    _require(gate.get("active") is True, f"{label} diagnostic gate is inactive")
    _require(gate.get("passed") is True, f"{label} diagnostic gate did not pass")
    _require(isinstance(release_gate, dict), f"{label} release gate declaration is missing")
    _require(release_gate.get("active") is False, f"{label} must not claim release-gate authority")
    _require(release_gate.get("passed") is None, f"{label} must not claim a release-gate result")
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


def _verify_red_team_provenance(report_payload: dict, red_team_payload: dict) -> None:
    report_run = report_payload["run"]
    red_team_run = red_team_payload["run"]
    _require(
        (report_run.get("git") or {}).get("commit") == (red_team_run.get("git") or {}).get("commit"),
        "Report and red-team evidence came from different Git commits",
    )
    for field in _INDEX_IDENTITY_FIELDS:
        _require(
            (report_run.get("rag_index") or {}).get(field) == (red_team_run.get("rag_index") or {}).get(field),
            f"Report and red-team evidence use different RAG index {field}",
        )
    _require(
        report_run.get("model") == red_team_run.get("model"),
        "Report and red-team evidence use different model identities or parameters",
    )
    _require(
        report_run.get("quality_policy") == red_team_run.get("quality_policy"),
        "Report and red-team evidence use different quality policies",
    )


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
    release_version: str | None = None,
    release_dir: Path | str | None = None,
    paths: ReleasePaths | None = None,
) -> dict:
    """Validate the complete committed release evidence set offline."""

    root = Path(project_root).resolve()
    try:
        selected_version = validate_release_version(release_version) if release_version is not None else None
        release_paths = paths or ReleasePaths.for_project(
            root,
            release_version=selected_version,
            release_dir=release_dir,
        )
    except ReleasePathError as error:
        raise ReleaseVerificationError(str(error)) from error
    if selected_version is not None:
        _require(
            release_paths.release_version == selected_version,
            "Explicit release version does not match the supplied release paths",
        )
    else:
        selected_version = release_paths.release_version

    current_project_version = _project_version(release_paths.pyproject)
    current_project_mode = release_version is None or selected_version == current_project_version
    if current_project_mode:
        _require(
            current_project_version == selected_version,
            f"Expected project version {selected_version}, found {current_project_version}",
        )

    rag_payload = _load_json(release_paths.rag_artifact, "RAG release artifact")
    report_payload = _load_json(release_paths.report_artifact, "Report release artifact")
    requires_red_team = release_version_tuple(selected_version) >= RED_TEAM_MINIMUM_VERSION
    red_team_payload = (
        _load_json(release_paths.red_team_artifact, "Red-team diagnostic artifact") if requires_red_team else None
    )
    try:
        validate_rag_evaluation_artifact(rag_payload)
        validate_report_evaluation_artifact(report_payload)
        if red_team_payload is not None:
            validate_report_evaluation_artifact(red_team_payload)
    except ArtifactValidationError as error:
        raise ReleaseVerificationError(f"Release artifact contract failed: {error}") from error

    _verify_release_gate(rag_payload, "RAG")
    _verify_release_gate(report_payload, "Report")
    if red_team_payload is not None:
        _verify_diagnostic_gate(red_team_payload, "Red-team")
    rag_question_source = _verify_dataset_binding(
        rag_payload["run"],
        source_path=release_paths.rag_questions,
        relative_path=RAG_QUESTIONS_PATH,
        file_field="questions_file",
        sha_field="questions_sha256",
        hash_basis_field="questions_hash_basis",
        schema_field="questions_schema_version",
    )
    _verify_rag_suite_binding(rag_payload, rag_question_source)
    report_scenario_source = _verify_dataset_binding(
        report_payload["run"],
        source_path=release_paths.report_scenarios,
        relative_path=report_scenario_relative_path(selected_version),
        file_field="scenario_file",
        sha_field="scenario_file_sha256",
        hash_basis_field="scenario_hash_basis" if requires_red_team else None,
        schema_field="scenario_schema_version",
    )
    _verify_scenario_suite_binding(report_payload, report_scenario_source, label="Report")
    if red_team_payload is not None:
        red_team_relative = Path("data_australia") / "rag" / f"report_red_team-v{selected_version}.json"
        red_team_scenario_source = _verify_dataset_binding(
            red_team_payload["run"],
            source_path=release_paths.red_team_scenarios,
            relative_path=red_team_relative,
            file_field="scenario_file",
            sha_field="scenario_file_sha256",
            hash_basis_field="scenario_hash_basis",
            schema_field="scenario_schema_version",
        )
        _verify_scenario_suite_binding(red_team_payload, red_team_scenario_source, label="Red-team")
        red_team_run = red_team_payload["run"]
        _require(
            red_team_run.get("scenario_suite_kind") == "prompt_injection_red_team",
            "Red-team artifact uses the wrong scenario suite kind",
        )
        _require(
            red_team_run.get("scenario_suite_version") == selected_version,
            "Red-team scenario suite version does not match the release",
        )
        _require(
            red_team_run.get("artifact_purpose") == "diagnostic_prompt_injection_red_team",
            "Red-team artifact purpose is invalid",
        )
        _require(
            report_payload["run"].get("scenario_suite_kind") == "product_regression",
            "Report artifact does not declare the product regression suite",
        )
        _require(
            report_payload["run"].get("scenario_suite_version") == selected_version,
            "Product report scenario suite version does not match the release",
        )

    current_policy = quality_policy_metadata()
    recorded_policy = report_payload["run"].get("quality_policy")
    _require(isinstance(recorded_policy, dict), "Report release artifact has no bound quality policy")
    if current_project_mode:
        _require(
            recorded_policy == current_policy, "Report release artifact is not bound to the current quality policy"
        )
    commit = _verify_shared_provenance(rag_payload, report_payload)
    if red_team_payload is not None:
        _verify_red_team_provenance(report_payload, red_team_payload)

    try:
        sample = verify_sample_package(
            release_paths.sample_package,
            standalone_dir=release_paths.sample_directory,
            require_current_policy=current_project_mode,
        )
    except ValueError as error:
        raise ReleaseVerificationError(f"Current showcase package failed verification: {error}") from error
    if current_project_mode:
        _require(sample.get("current_policy") is True, "Showcase package is not bound to the current quality policy")
    _require(sample.get("governed_gate_passed") is True, "Showcase package did not pass the governed report gate")
    _require(sample.get("quality_policy_version") == recorded_policy.get("version"), "Showcase policy version is stale")
    _require(
        sample.get("quality_policy_fingerprint") == recorded_policy.get("fingerprint"),
        "Showcase policy fingerprint is stale",
    )
    _verify_sample_runtime(sample, rag_payload, report_payload)

    result = {
        "release_version": selected_version,
        "project_version": current_project_version,
        "verification_mode": "project_current" if current_project_mode else "immutable_release",
        "verified_offline": True,
        "source_commit": commit,
        "quality_policy_version": recorded_policy["version"],
        "quality_policy_fingerprint": recorded_policy["fingerprint"],
        "rag_release_gate_passed": True,
        "report_release_gate_passed": True,
        "sample": sample,
    }
    if red_team_payload is not None:
        result["red_team_diagnostic_gate_passed"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--release-version",
        help=(
            "Verify an immutable major.minor.patch release independently of the current project version. "
            "Omit this option to verify the version declared by pyproject.toml against current policy."
        ),
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="Override the versioned sample directory; it must remain inside the project root.",
    )
    args = parser.parse_args(argv)
    try:
        result = verify_release(
            args.project_root,
            release_version=args.release_version,
            release_dir=args.release_dir,
        )
    except ReleaseVerificationError as error:
        parser.exit(1, f"Release verification failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
