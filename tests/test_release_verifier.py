import copy
import json

import pytest

from scripts import verify_release as release_verifier
from scripts.evaluation_artifacts import sha256_file
from src.report_generation_quality import quality_policy_metadata


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def release_fixture(tmp_path, monkeypatch):
    paths = release_verifier.ReleasePaths.for_project(tmp_path)
    paths.pyproject.write_text('[project]\nversion = "0.5.0"\n', encoding="utf-8")
    questions = {"schema_version": 3, "questions": []}
    scenarios = {"schema_version": 2, "scenarios": []}
    _write_json(paths.rag_questions, questions)
    _write_json(paths.report_scenarios, scenarios)
    commit = "a" * 40
    index = {
        "schema": "bushfire-rag-index-v3",
        "manifest_sha256": "b" * 64,
        "catalog_sha256": "c" * 64,
        "corpus_sha256": "d" * 64,
        "documents_sha256": "e" * 64,
        "embedding_dimension": 768,
        "source_count": 14,
        "chunk_count": 123,
    }
    common_git = {"commit": commit, "working_tree_dirty": False, "collection_status": "collected"}
    rag_payload = {
        "passed": True,
        "release_gate": {"active": True, "passed": True},
        "run": {
            "questions_file": release_verifier.RAG_QUESTIONS_PATH.as_posix(),
            "questions_sha256": sha256_file(paths.rag_questions),
            "questions_hash_basis": "exact_file_bytes",
            "questions_schema_version": 3,
            "git": common_git,
            "rag_index": index,
        },
    }
    report_payload = {
        "passed": True,
        "release_gate": {"active": True, "passed": True},
        "run": {
            "scenario_file": release_verifier.REPORT_SCENARIOS_PATH.as_posix(),
            "scenario_file_sha256": sha256_file(paths.report_scenarios),
            "scenario_schema_version": 2,
            "git": common_git,
            "rag_index": index,
            "quality_policy": quality_policy_metadata(),
            "model": {
                "provider": "ollama",
                "name": "bushfire-ready-qwen",
            },
        },
    }
    _write_json(paths.rag_artifact, rag_payload)
    _write_json(paths.report_artifact, report_payload)
    paths.sample_package.parent.mkdir(parents=True, exist_ok=True)
    paths.sample_package.write_bytes(b"test fixture")
    sample_result = {
        "current_policy": True,
        "governed_gate_passed": True,
        "quality_policy_version": quality_policy_metadata()["version"],
        "quality_policy_fingerprint": quality_policy_metadata()["fingerprint"],
        "rag_index_manifest_sha256": index["manifest_sha256"],
        "model_provider": "ollama",
        "model_name": "bushfire-ready-qwen",
        "model_endpoint_boundary": "local_loopback",
    }
    calls = {"rag": 0, "report": 0, "sample": 0}

    def validate_rag(payload):
        calls["rag"] += 1
        return payload

    def validate_report(payload):
        calls["report"] += 1
        return payload

    def verify_sample(package_path, *, standalone_dir, require_current_policy):
        calls["sample"] += 1
        assert package_path == paths.sample_package
        assert standalone_dir == paths.sample_directory
        assert require_current_policy is True
        return sample_result

    monkeypatch.setattr(release_verifier, "validate_rag_evaluation_artifact", validate_rag)
    monkeypatch.setattr(release_verifier, "validate_report_evaluation_artifact", validate_report)
    monkeypatch.setattr(release_verifier, "verify_sample_package", verify_sample)
    return tmp_path, paths, rag_payload, report_payload, calls


def test_verify_release_accepts_current_offline_evidence(release_fixture):
    root, paths, _rag, _report, calls = release_fixture

    result = release_verifier.verify_release(root, paths=paths)

    assert result["release_version"] == "0.5.0"
    assert result["verified_offline"] is True
    assert result["rag_release_gate_passed"] is True
    assert result["report_release_gate_passed"] is True
    assert calls == {"rag": 1, "report": 1, "sample": 1}


def test_verify_release_rejects_wrong_project_version(release_fixture):
    root, paths, _rag, _report, _calls = release_fixture
    paths.pyproject.write_text('[project]\nversion = "0.4.0"\n', encoding="utf-8")

    with pytest.raises(release_verifier.ReleaseVerificationError, match="Expected project version 0.5.0"):
        release_verifier.verify_release(root, paths=paths)


@pytest.mark.parametrize("artifact", ["rag", "report"])
def test_verify_release_requires_active_passing_release_gates(release_fixture, artifact):
    root, paths, rag_payload, report_payload, _calls = release_fixture
    payload = copy.deepcopy(rag_payload if artifact == "rag" else report_payload)
    payload["release_gate"]["active"] = False
    target = paths.rag_artifact if artifact == "rag" else paths.report_artifact
    _write_json(target, payload)

    with pytest.raises(release_verifier.ReleaseVerificationError, match="release gate is inactive"):
        release_verifier.verify_release(root, paths=paths)


def test_verify_release_rejects_stale_source_hash(release_fixture):
    root, paths, _rag, _report, _calls = release_fixture
    _write_json(paths.rag_questions, {"schema_version": 3, "questions": [{"id": "new"}]})

    with pytest.raises(release_verifier.ReleaseVerificationError, match="stale evaluation.json SHA"):
        release_verifier.verify_release(root, paths=paths)


def test_verify_release_rejects_stale_quality_policy(release_fixture):
    root, paths, _rag, report_payload, _calls = release_fixture
    payload = copy.deepcopy(report_payload)
    payload["run"]["quality_policy"]["fingerprint"] = "f" * 64
    _write_json(paths.report_artifact, payload)

    with pytest.raises(release_verifier.ReleaseVerificationError, match="current quality policy"):
        release_verifier.verify_release(root, paths=paths)


def test_verify_release_requires_shared_git_and_index_provenance(release_fixture):
    root, paths, _rag, report_payload, _calls = release_fixture
    payload = copy.deepcopy(report_payload)
    payload["run"]["git"]["commit"] = "9" * 40
    _write_json(paths.report_artifact, payload)

    with pytest.raises(release_verifier.ReleaseVerificationError, match="different Git commits"):
        release_verifier.verify_release(root, paths=paths)


def test_verify_release_requires_sample_runtime_to_match_benchmarks(release_fixture, monkeypatch):
    root, paths, _rag, _report, _calls = release_fixture
    current_policy = quality_policy_metadata()
    sample = {
        "current_policy": True,
        "governed_gate_passed": True,
        "quality_policy_version": current_policy["version"],
        "quality_policy_fingerprint": current_policy["fingerprint"],
        "rag_index_manifest_sha256": "9" * 64,
        "model_provider": "ollama",
        "model_name": "bushfire-ready-qwen",
        "model_endpoint_boundary": "local_loopback",
    }
    monkeypatch.setattr(release_verifier, "verify_sample_package", lambda *_args, **_kwargs: sample)

    with pytest.raises(release_verifier.ReleaseVerificationError, match="different RAG index"):
        release_verifier.verify_release(root, paths=paths)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("model_endpoint_boundary", "external", "local loopback"),
        ("model_provider", "openai", "both use Ollama"),
        ("model_name", "another-model", "different model names"),
    ),
)
def test_verify_release_rejects_mismatched_sample_model_runtime(
    release_fixture,
    monkeypatch,
    field,
    value,
    message,
):
    root, paths, _rag, _report, _calls = release_fixture
    current_policy = quality_policy_metadata()
    sample = {
        "current_policy": True,
        "governed_gate_passed": True,
        "quality_policy_version": current_policy["version"],
        "quality_policy_fingerprint": current_policy["fingerprint"],
        "rag_index_manifest_sha256": "b" * 64,
        "model_provider": "ollama",
        "model_name": "bushfire-ready-qwen",
        "model_endpoint_boundary": "local_loopback",
        field: value,
    }
    monkeypatch.setattr(release_verifier, "verify_sample_package", lambda *_args, **_kwargs: sample)

    with pytest.raises(release_verifier.ReleaseVerificationError, match=message):
        release_verifier.verify_release(root, paths=paths)
