import copy
import json

import pytest

from scripts import verify_release as release_verifier
from scripts.evaluation_artifacts import sha256_file
from src.report_generation_quality import quality_policy_metadata


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


RAG_THRESHOLDS = {
    "passage_recall_at_k": 0.9,
    "mean_reciprocal_rank": 0.75,
    "unanswerable_accuracy": 0.8,
}
REPORT_THRESHOLDS_V2 = {
    "governed_gate_rate": 1.0,
    "evidence_binding_rate": 1.0,
}
REPORT_THRESHOLDS_V3 = {
    **REPORT_THRESHOLDS_V2,
    "repair_success_rate": 1.0,
    "repair_exhaustion_rate": 0.0,
}
RED_TEAM_THRESHOLDS_V3 = {
    **REPORT_THRESHOLDS_V3,
    "prompt_injection_resistance_rate": 1.0,
}


def _selection(scenarios, *, include_kinds):
    scenario_ids = [scenario["id"] for scenario in scenarios]
    selection = {
        "declared_scenarios": len(scenarios),
        "selected_scenarios": len(scenarios),
        "declared_scenario_ids": scenario_ids,
        "selected_scenario_ids": scenario_ids,
        "complete": True,
    }
    if include_kinds:
        selection["declared_scenario_kinds"] = [
            {
                "id": scenario["id"],
                "kind": scenario.get("kind", "product_scenario"),
                "attack_surface": scenario.get("attack_surface"),
            }
            for scenario in scenarios
        ]
    return selection


@pytest.fixture
def release_fixture(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.5.0"\n', encoding="utf-8")
    paths = release_verifier.ReleasePaths.for_project(tmp_path)
    questions = {
        "schema_version": 3,
        "thresholds": copy.deepcopy(RAG_THRESHOLDS),
        "questions": [
            {"id": "rag_question_legacy"},
            {"id": "rag_question_free_text", "evaluation_profiles": ["free_text"]},
        ],
    }
    product_scenarios = [{"id": "product_scenario_legacy"}]
    scenarios = {
        "schema_version": 2,
        "suite_kind": None,
        "suite_version": None,
        "thresholds": copy.deepcopy(REPORT_THRESHOLDS_V2),
        "scenarios": product_scenarios,
    }
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
        "release_gate": {"active": True, "passed": True, "profile": "structured_planning"},
        "run": {
            "questions_file": release_verifier.RAG_QUESTIONS_PATH.as_posix(),
            "questions_sha256": sha256_file(paths.rag_questions),
            "questions_hash_basis": "exact_file_bytes",
            "questions_schema_version": 3,
            "git": common_git,
            "rag_index": index,
        },
        "profiles": {
            "structured_planning": {
                "thresholds": copy.deepcopy(RAG_THRESHOLDS),
                "rows": [{"id": "rag_question_legacy"}],
            },
            "free_text": {
                "thresholds": copy.deepcopy(RAG_THRESHOLDS),
                "rows": [{"id": "rag_question_legacy"}, {"id": "rag_question_free_text"}],
            },
        },
    }
    report_payload = {
        "passed": True,
        "release_gate": {"active": True, "passed": True},
        "thresholds": copy.deepcopy(REPORT_THRESHOLDS_V2),
        "selection": _selection(product_scenarios, include_kinds=False),
        "run": {
            "scenario_file": release_verifier.REPORT_SCENARIOS_PATH.as_posix(),
            "scenario_file_sha256": sha256_file(paths.report_scenarios),
            "scenario_schema_version": 2,
            "scenario_suite_kind": None,
            "scenario_suite_version": None,
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
    calls = {"rag": 0, "report": 0, "sample": 0, "sample_current_policy": []}

    def validate_rag(payload):
        calls["rag"] += 1
        return payload

    def validate_report(payload):
        calls["report"] += 1
        return payload

    def verify_sample(package_path, *, standalone_dir, require_current_policy):
        calls["sample"] += 1
        calls["sample_current_policy"].append(require_current_policy)
        assert package_path == standalone_dir / "cairns-council-pilot-package.zip"
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
    assert calls == {"rag": 1, "report": 1, "sample": 1, "sample_current_policy": [True]}


def test_explicit_current_version_keeps_strict_current_policy_mode(release_fixture):
    root, paths, _rag, _report, calls = release_fixture

    result = release_verifier.verify_release(root, paths=paths, release_version="0.5.0")

    assert result["verification_mode"] == "project_current"
    assert calls["sample_current_policy"] == [True]


def test_explicit_v050_remains_verifiable_after_project_advances(release_fixture):
    root, paths, _rag, _report, calls = release_fixture
    paths.pyproject.write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")

    result = release_verifier.verify_release(root, paths=paths, release_version="0.5.0")

    assert result["release_version"] == "0.5.0"
    assert result["project_version"] == "0.6.0"
    assert result["verification_mode"] == "immutable_release"
    assert calls["sample_current_policy"] == [False]


def test_release_paths_follow_current_or_explicit_future_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")

    current = release_verifier.ReleasePaths.for_project(tmp_path)
    explicit = release_verifier.ReleasePaths.for_project(tmp_path, release_version="0.5.0")

    assert current.release_version == "0.6.0"
    assert current.rag_artifact == tmp_path / "docs/benchmarks/rag-retrieval-v0.6.0.json"
    assert current.report_artifact == tmp_path / "docs/benchmarks/report-generation-v0.6.0.json"
    assert current.red_team_artifact == tmp_path / "docs/benchmarks/report-red-team-v0.6.0.json"
    assert current.red_team_scenarios == tmp_path / "data_australia/rag/report_red_team-v0.6.0.json"
    assert current.report_scenarios == tmp_path / "data_australia/rag/report_evaluation-v0.6.0.json"
    assert current.sample_directory == tmp_path / "examples/v0.6.0"
    assert explicit.release_version == "0.5.0"
    assert explicit.report_scenarios == tmp_path / "data_australia/rag/report_evaluation.json"
    assert explicit.sample_directory == tmp_path / "examples/v0.5.0"


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


@pytest.mark.parametrize(
    ("binding", "message"),
    (
        ("thresholds", "RAG profile structured_planning thresholds do not match"),
        ("question_ids", "RAG profile structured_planning question IDs do not match"),
    ),
)
def test_verify_release_rejects_rag_suite_semantic_tampering(release_fixture, binding, message):
    root, paths, rag_payload, _report, _calls = release_fixture
    payload = copy.deepcopy(rag_payload)
    profile = payload["profiles"]["structured_planning"]
    if binding == "thresholds":
        profile["thresholds"]["passage_recall_at_k"] = 0.1
    else:
        profile["rows"][0]["id"] = "unbound_question"
    _write_json(paths.rag_artifact, payload)

    with pytest.raises(release_verifier.ReleaseVerificationError, match=message):
        release_verifier.verify_release(root, paths=paths)


def test_verify_release_binds_rag_profile_selection_and_threshold_overrides(release_fixture):
    root, paths, rag_payload, _report, _calls = release_fixture
    questions = _read_json(paths.rag_questions)
    questions["profile_thresholds"] = {"free_text": {"mean_reciprocal_rank": 0.7}}
    _write_json(paths.rag_questions, questions)

    payload = copy.deepcopy(rag_payload)
    payload["run"]["questions_sha256"] = sha256_file(paths.rag_questions)
    payload["profiles"]["free_text"]["thresholds"]["mean_reciprocal_rank"] = 0.7
    _write_json(paths.rag_artifact, payload)

    assert release_verifier.verify_release(root, paths=paths)["verified_offline"] is True

    payload["profiles"].pop("free_text")
    _write_json(paths.rag_artifact, payload)
    with pytest.raises(release_verifier.ReleaseVerificationError, match="RAG artifact profiles do not match"):
        release_verifier.verify_release(root, paths=paths)


@pytest.mark.parametrize(
    ("binding", "message"),
    (
        ("thresholds", "Report artifact thresholds do not match"),
        ("scenario_ids", "Report artifact scenario IDs do not match"),
    ),
)
def test_verify_release_rejects_legacy_report_suite_semantic_tampering(release_fixture, binding, message):
    root, paths, _rag, report_payload, _calls = release_fixture
    payload = copy.deepcopy(report_payload)
    if binding == "thresholds":
        payload["thresholds"]["governed_gate_rate"] = 0.5
    else:
        payload["selection"]["declared_scenario_ids"][0] = "unbound_scenario"
    _write_json(paths.report_artifact, payload)

    with pytest.raises(release_verifier.ReleaseVerificationError, match=message):
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


def _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload):
    old_paths.pyproject.write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")
    paths = release_verifier.ReleasePaths.for_project(root)
    questions = {
        "schema_version": 3,
        "thresholds": copy.deepcopy(RAG_THRESHOLDS),
        "questions": [{"id": "rag_question_v060"}],
    }
    product_scenarios = [{"id": "product_scenario_v060", "kind": "product_scenario"}]
    red_team_scenarios = [
        {
            "id": "red_team_scenario_v060",
            "kind": "prompt_injection_red_team",
            "attack_surface": "u0_extra_context",
        }
    ]
    _write_json(paths.rag_questions, questions)
    _write_json(
        paths.report_scenarios,
        {
            "schema_version": 3,
            "suite_kind": "product_regression",
            "suite_version": "0.6.0",
            "thresholds": copy.deepcopy(REPORT_THRESHOLDS_V3),
            "scenarios": product_scenarios,
        },
    )
    _write_json(
        paths.red_team_scenarios,
        {
            "schema_version": 3,
            "suite_kind": "prompt_injection_red_team",
            "suite_version": "0.6.0",
            "thresholds": copy.deepcopy(RED_TEAM_THRESHOLDS_V3),
            "scenarios": red_team_scenarios,
        },
    )
    rag = copy.deepcopy(rag_payload)
    rag["run"]["questions_sha256"] = sha256_file(paths.rag_questions)
    rag["profiles"]["structured_planning"].update(
        {
            "thresholds": copy.deepcopy(RAG_THRESHOLDS),
            "rows": [{"id": "rag_question_v060"}],
        }
    )
    rag["profiles"]["free_text"].update(
        {
            "thresholds": copy.deepcopy(RAG_THRESHOLDS),
            "rows": [{"id": "rag_question_v060"}],
        }
    )
    report = copy.deepcopy(report_payload)
    report["thresholds"] = copy.deepcopy(REPORT_THRESHOLDS_V3)
    report["selection"] = _selection(product_scenarios, include_kinds=True)
    report["run"].update(
        {
            "scenario_file": paths.report_scenarios.relative_to(root).as_posix(),
            "scenario_file_sha256": sha256_file(paths.report_scenarios),
            "scenario_hash_basis": "exact_file_bytes",
            "scenario_schema_version": 3,
            "scenario_suite_kind": "product_regression",
            "scenario_suite_version": "0.6.0",
        }
    )
    red_team = copy.deepcopy(report)
    red_team.update(
        {
            "release_gate": {"active": False, "passed": None},
            "diagnostic_gate": {"active": True, "passed": True},
            "thresholds": copy.deepcopy(RED_TEAM_THRESHOLDS_V3),
            "selection": _selection(red_team_scenarios, include_kinds=True),
        }
    )
    red_team["run"].update(
        {
            "artifact_purpose": "diagnostic_prompt_injection_red_team",
            "scenario_file": "data_australia/rag/report_red_team-v0.6.0.json",
            "scenario_file_sha256": sha256_file(paths.red_team_scenarios),
            "scenario_schema_version": 3,
            "scenario_suite_kind": "prompt_injection_red_team",
            "scenario_suite_version": "0.6.0",
        }
    )
    _write_json(paths.rag_artifact, rag)
    _write_json(paths.report_artifact, report)
    _write_json(paths.red_team_artifact, red_team)
    paths.sample_package.parent.mkdir(parents=True, exist_ok=True)
    paths.sample_package.write_bytes(b"test fixture")
    return paths, red_team


def test_v060_release_requires_passing_bound_red_team_evidence(release_fixture):
    root, old_paths, rag_payload, report_payload, calls = release_fixture
    paths, _red_team = _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload)

    result = release_verifier.verify_release(root, paths=paths)

    assert result["red_team_diagnostic_gate_passed"] is True
    assert calls["report"] == 2


@pytest.mark.parametrize(
    ("binding", "message"),
    (
        ("scenario_kind", "Report artifact scenario kinds do not match"),
        ("suite_version", "Report artifact suite version does not match"),
    ),
)
def test_v060_release_rejects_product_suite_semantic_tampering(
    release_fixture,
    binding,
    message,
):
    root, old_paths, rag_payload, report_payload, _calls = release_fixture
    paths, _red_team = _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload)
    product = _read_json(paths.report_artifact)
    if binding == "scenario_kind":
        product["selection"]["declared_scenario_kinds"][0]["kind"] = "prompt_injection_red_team"
    else:
        product["run"]["scenario_suite_version"] = "0.6.1"
    _write_json(paths.report_artifact, product)

    with pytest.raises(release_verifier.ReleaseVerificationError, match=message):
        release_verifier.verify_release(root, paths=paths)


@pytest.mark.parametrize(
    ("binding", "message"),
    (
        ("thresholds", "Red-team artifact thresholds do not match"),
        ("scenario_ids", "Red-team artifact scenario IDs do not match"),
        ("scenario_kind", "Red-team artifact scenario kinds do not match"),
        ("suite_version", "Red-team artifact suite version does not match"),
    ),
)
def test_v060_release_rejects_red_team_suite_semantic_tampering(
    release_fixture,
    binding,
    message,
):
    root, old_paths, rag_payload, report_payload, _calls = release_fixture
    paths, red_team = _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload)
    if binding == "thresholds":
        red_team["thresholds"]["prompt_injection_resistance_rate"] = 0.5
    elif binding == "scenario_ids":
        red_team["selection"]["declared_scenario_ids"][0] = "unbound_red_team_scenario"
    elif binding == "scenario_kind":
        red_team["selection"]["declared_scenario_kinds"][0]["kind"] = "product_scenario"
    else:
        red_team["run"]["scenario_suite_version"] = "0.6.1"
    _write_json(paths.red_team_artifact, red_team)

    with pytest.raises(release_verifier.ReleaseVerificationError, match=message):
        release_verifier.verify_release(root, paths=paths)


def test_v060_release_rejects_stale_red_team_dataset(release_fixture):
    root, old_paths, rag_payload, report_payload, _calls = release_fixture
    paths, _red_team = _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload)
    _write_json(paths.red_team_scenarios, {"schema_version": 3, "scenarios": [{"id": "changed"}]})

    with pytest.raises(release_verifier.ReleaseVerificationError, match="stale report_red_team-v0.6.0.json SHA"):
        release_verifier.verify_release(root, paths=paths)


def test_v060_red_team_cannot_claim_release_gate_authority(release_fixture):
    root, old_paths, rag_payload, report_payload, _calls = release_fixture
    paths, red_team = _upgrade_fixture_to_v060(root, old_paths, rag_payload, report_payload)
    red_team["release_gate"] = {"active": True, "passed": True}
    _write_json(paths.red_team_artifact, red_team)

    with pytest.raises(release_verifier.ReleaseVerificationError, match="must not claim release-gate authority"):
        release_verifier.verify_release(root, paths=paths)
