"""CLI capture and publication guards, with synthetic SDK calls only."""

import copy
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from scripts import build_showcase_sample as showcase
from scripts import evaluate_report_generation as evaluation
from src import audit, export_package
from src import report_generation_quality as generation
from src.export_register import REGISTER_SNAPSHOT_FILES
from src.model_evidence import text_sha256, validate_model_evidence
from src.model_runtime import GovernedModelClient
from src.rag.context import assemble_planning_context


def _analysis():
    text = "Families prepare household emergency supplies. " * 65
    chunk = {
        "source_id": "synthetic_guide",
        "chunk_id": "synthetic_guide-1",
        "title": "Synthetic guidance",
        "agency": "Synthetic authority",
        "text": text,
        "chunk_sha256": text_sha256(text),
        "jurisdictions": ["Queensland"],
        "url": "https://example.gov.au/synthetic",
    }
    analysis = {
        "profile": {"state": "Queensland"},
        "knowledge": {"status": "ready", "retrieved_chunks": [chunk], "index_manifest_sha256": "a" * 64},
        "data": {"sources": [{"id": "one", "name": "Official One"}, {"id": "two", "name": "Official Two"}]},
    }
    analysis["rag_context_assembly"] = assemble_planning_context(analysis["knowledge"])
    return analysis


def _scenario():
    return {
        "id": "synthetic_cli",
        "location": "Cairns",
        "audience": "community",
        "scenario": "Council Preparedness",
        "concerns": ["supplies"],
        "timeframe": "7 days",
        "extra_context": "PRIVATE CLI FORM VALUE",
    }


def _narrative():
    return "[O1-RAG][source_id=synthetic_guide] Synthetic guidance says families prepare household emergency supplies."


def _setup(monkeypatch, *, attempts=1, protocol_failure=False, fake=False):
    analysis = _analysis()
    prompts = []
    callbacks = []
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "0")
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_CONCURRENT", "0")
    monkeypatch.setattr(evaluation, "run_analysis_pipeline", lambda *_: analysis)
    monkeypatch.setattr(
        evaluation,
        "build_report_prompt",
        lambda *_, **__: "PRIVATE CLI FORM VALUE\n" + analysis["rag_context_assembly"]["context"],
    )

    def create(**kwargs):
        prompts.append(copy.deepcopy(list(kwargs["messages"])))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=_narrative()),
                    finish_reason="length" if protocol_failure and len(prompts) == 1 else "stop",
                )
            ]
        )

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runtime = GovernedModelClient(completion_client=sdk, provider="synthetic", is_local=False)
    if fake:
        runtime = SimpleNamespace(generate=lambda _: _narrative())
    monkeypatch.setattr(evaluation, "GovernedModelClient", lambda: runtime)

    def assess(*args):
        callbacks.append(True)
        return {"approval_gate": {"passed": len(callbacks) >= attempts}}

    monkeypatch.setattr(generation, "assess_generated_narrative", assess)
    monkeypatch.setattr(evaluation, "apply_governance_notice", lambda text: text)
    monkeypatch.setattr(evaluation, "append_evidence_tables", lambda text, _: text)
    monkeypatch.setattr(evaluation, "append_human_signoff", lambda text, _: text)
    monkeypatch.setattr(
        evaluation,
        "evaluate_governed_report",
        lambda *_: {
            "approval_gate": {"passed": True, "blocking_failures": []},
            "checks": [],
            "quality_policy_version": generation.QUALITY_POLICY_VERSION,
            "quality_policy_fingerprint": generation.QUALITY_POLICY_FINGERPRINT,
        },
    )
    return analysis, prompts


@pytest.mark.parametrize("attempts", [1, 2])
def test_cli_returns_final_successful_sdk_capture_and_only_hashed_public_metadata(monkeypatch, attempts):
    analysis, prompts = _setup(monkeypatch, attempts=attempts)
    result = evaluation.run_scenario_with_artifacts(_scenario())
    snapshot = result["model_evidence"]
    assert result["grounding_evaluation"]["model_visible_rag"]["snapshot"] == snapshot
    assert snapshot["attempt_number"] == attempts
    assert snapshot["request_kind"] == ("initial" if attempts == 1 else "structural_repair")
    assert snapshot["request_binding"]["user_prompt_sha256"] == text_sha256(prompts[-1][1]["content"])
    assert snapshot["assembly_manifest"]["max_chunk_characters"] == (2200 if attempts == 1 else 900)
    validate_model_evidence(snapshot, analysis, report_text=result["report"])
    summary = result["row"]["model_visible_rag"]
    assert summary["schema"] == "model-visible-rag-summary-v1"
    assert summary["attempt_number"] == attempts and summary["capture_status"] == "captured"
    assert summary["release_gate_enforced"] is False
    public = json.dumps(result["row"])
    assert "PRIVATE CLI FORM VALUE" not in public
    assert "Families prepare household emergency supplies." not in public
    assert "visible_passages" not in public and "assembly_manifest" not in public
    assert "PRIVATE CLI FORM VALUE" not in json.dumps(snapshot)


def test_cli_protocol_retry_captures_retry_prompt_not_failed_first_attempt(monkeypatch):
    analysis, prompts = _setup(monkeypatch, protocol_failure=True)
    result = evaluation.run_scenario_with_artifacts(_scenario())
    snapshot = result["model_evidence"]
    assert len(prompts) == 2 and snapshot["attempt_number"] == 2
    assert snapshot["request_kind"] == "protocol_retry"
    assert snapshot["request_binding"]["user_prompt_sha256"] == text_sha256(prompts[1][1]["content"])
    assert snapshot["request_binding"]["user_prompt_sha256"] != text_sha256(prompts[0][1]["content"])
    validate_model_evidence(snapshot, analysis, report_text=result["report"])


def test_cli_fake_client_is_unknown_and_does_not_reconstruct_an_actual_capture(monkeypatch):
    _setup(monkeypatch, fake=True)
    result = evaluation.run_scenario_with_artifacts(_scenario())
    assert result["model_evidence"]["status"] == "unavailable"
    assert result["row"]["model_visible_rag"]["capture_status"] == "unavailable"
    assert result["row"]["model_visible_rag"]["sdk_messages_sha256"] is None
    assert result["row"]["model_visible_rag"]["metrics"]["support_rate"] is None


@pytest.mark.parametrize(
    "state",
    [
        {"commit": "a" * 40, "working_tree_dirty": True, "collection_status": "collected"},
        {"commit": None, "working_tree_dirty": None, "collection_status": "unavailable"},
    ],
)
def test_showcase_refuses_dirty_or_unknown_source_before_model_or_outputs(monkeypatch, tmp_path, state):
    monkeypatch.setattr(showcase, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(showcase, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(showcase, "git_provenance", lambda _: state)
    monkeypatch.setattr(showcase, "run_scenario_with_artifacts", lambda _: pytest.fail("unexpected model call"))
    with pytest.raises(RuntimeError, match="verified clean Git source"):
        showcase.build_showcase_sample(tmp_path)
    assert not list(tmp_path.iterdir())


def test_showcase_refuses_source_change_during_generation_before_audit_or_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr(showcase, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(showcase, "MODEL_ENDPOINT_IS_LOCAL", True)
    states = iter(
        [
            {"commit": "a" * 40, "working_tree_dirty": False, "collection_status": "collected"},
            {"commit": "b" * 40, "working_tree_dirty": False, "collection_status": "collected"},
        ]
    )
    monkeypatch.setattr(showcase, "git_provenance", lambda _: next(states))
    monkeypatch.setattr(showcase, "run_scenario_with_artifacts", lambda _: {})
    monkeypatch.setattr(showcase, "save_report_audit", lambda _: pytest.fail("unexpected audit write"))
    with pytest.raises(RuntimeError, match="provenance changed"):
        showcase.build_showcase_sample(tmp_path)
    assert not list(tmp_path.iterdir())


def _showcase_with_actual_audit_and_package(monkeypatch, *, attempts=2):
    _setup(monkeypatch, attempts=attempts)
    artifacts = evaluation.run_scenario_with_artifacts(_scenario())
    fixed_quality = {
        "checks": [],
        "summary": {"passed": 1, "warnings": 0, "failed": 0, "total": 1},
        "approval_gate": {"passed": True, "status": "passed", "blocking_failures": []},
        "quality_policy_version": generation.QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": generation.QUALITY_POLICY_FINGERPRINT,
    }
    monkeypatch.setattr(showcase, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(showcase, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(
        showcase,
        "git_provenance",
        lambda _: {
            "commit": "a" * 40,
            "working_tree_dirty": False,
            "collection_status": "collected",
        },
    )
    monkeypatch.setattr(showcase, "run_scenario_with_artifacts", lambda _: artifacts)
    for module in (showcase, audit, export_package):
        monkeypatch.setattr(module, "evaluate_governed_report", lambda *_: copy.deepcopy(fixed_quality))
    monkeypatch.setattr(
        showcase,
        "build_export_register_snapshot",
        lambda: {name: "Synthetic register\n" for name in REGISTER_SNAPSHOT_FILES},
    )
    monkeypatch.setattr(export_package, "create_report_pdf", lambda _: b"synthetic PDF bytes")
    monkeypatch.setattr(export_package, "create_report_docx", lambda _: b"synthetic DOCX bytes")
    return artifacts


def test_showcase_final_repair_snapshot_is_bound_through_real_audit_and_zip(monkeypatch, tmp_path):
    artifacts = _showcase_with_actual_audit_and_package(monkeypatch)
    summary = showcase.build_showcase_sample(tmp_path)
    with ZipFile(BytesIO((tmp_path / "cairns-council-pilot-package.zip").read_bytes())) as package:
        grounding_bytes = package.read("governance/grounding_evaluation.json")
        grounding = json.loads(grounding_bytes)
        event = json.loads(package.read("governance/audit_record.json"))
        manifest = json.loads(package.read("governance/package_manifest.json"))
    snapshot = grounding["model_visible_rag"]["snapshot"]
    assert snapshot == artifacts["model_evidence"]
    assert snapshot["attempt_number"] == 2 and snapshot["request_kind"] == "structural_repair"
    assert snapshot["assembly_manifest"]["max_chunk_characters"] == 900
    assert event["grounding_evaluation_hash"] == audit.sha256_json(grounding)
    assert manifest["artifact_hashes"]["governance/grounding_evaluation.json"] == text_sha256(grounding_bytes.decode())
    assert summary["model_evidence_sha256"] == audit.sha256_json(snapshot)
    assert summary["source_provenance"]["commit"] == "a" * 40
    assert "PRIVATE CLI FORM VALUE" not in grounding_bytes.decode()


@pytest.mark.parametrize("kind", ["missing", "changed_narrative"])
def test_showcase_cannot_publish_missing_or_different_final_capture(monkeypatch, tmp_path, kind):
    artifacts = _showcase_with_actual_audit_and_package(monkeypatch)
    if kind == "missing":
        artifacts.pop("model_evidence")
    else:
        artifacts["model_evidence"]["normalized_narrative_sha256"] = "0" * 64
    monkeypatch.setattr(showcase, "save_report_audit", lambda _: pytest.fail("unexpected audit write"))
    with pytest.raises(RuntimeError, match="snapshot"):
        showcase.build_showcase_sample(tmp_path)
    assert not list(tmp_path.iterdir())


def test_showcase_checks_clean_source_again_immediately_before_publication(monkeypatch, tmp_path):
    _showcase_with_actual_audit_and_package(monkeypatch)
    count = [0]

    def changing(_):
        count[0] += 1
        return {"commit": "a" * 40, "working_tree_dirty": count[0] == 3, "collection_status": "collected"}

    monkeypatch.setattr(showcase, "git_provenance", changing)
    with pytest.raises(RuntimeError, match="verified clean Git source"):
        showcase.build_showcase_sample(tmp_path)
    assert count[0] == 3
    assert not list(tmp_path.iterdir())
