import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from scripts import build_showcase_sample
from src.model_evidence import EvidencePrompt, bind_normalized_narrative, capture_model_evidence
from src.model_runtime import GovernedModelClient
from src.rag.context import assemble_planning_context


@pytest.fixture(autouse=True)
def _synthetic_clean_source(monkeypatch):
    monkeypatch.setattr(
        build_showcase_sample,
        "git_provenance",
        lambda _: {"commit": "a" * 40, "working_tree_dirty": False, "collection_status": "collected"},
    )


def _recorded_synthetic_snapshot(analysis, report="Synthetic draft"):
    assembly = assemble_planning_context(analysis["knowledge"])
    prompt = EvidencePrompt(assembly["context"], assembly=assembly)
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=report),
                            finish_reason="stop",
                        )
                    ]
                ),
            )
        )
    )
    runtime = GovernedModelClient(completion_client=sdk, provider="synthetic", is_local=False)
    response = runtime.generate(prompt)
    return bind_normalized_narrative(capture_model_evidence(prompt, runtime, response, attempt_number=1), response)


@pytest.mark.parametrize("name", build_showcase_sample._OUTPUT_NAMES)
def test_showcase_preserves_existing_evidence_before_model_call(tmp_path, monkeypatch, name):
    original = b"frozen historical evidence"
    existing = tmp_path / name
    existing.write_bytes(original)
    monkeypatch.setattr(build_showcase_sample, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(build_showcase_sample, "MODEL_ENDPOINT_IS_LOCAL", True)

    def forbidden_generation(_scenario):
        pytest.fail("An occupied destination must fail before invoking a model")

    monkeypatch.setattr(build_showcase_sample, "run_scenario_with_artifacts", forbidden_generation)
    with pytest.raises(FileExistsError, match="new --output-dir"):
        build_showcase_sample.build_showcase_sample(tmp_path)

    assert existing.read_bytes() == original
    assert list(tmp_path.iterdir()) == [existing]


def test_showcase_allows_readme_but_rejects_partial_sample(tmp_path):
    (tmp_path / "README.md").write_text("New unreleased sample", encoding="utf-8")
    build_showcase_sample._require_unused_outputs(tmp_path)
    (tmp_path / build_showcase_sample._OUTPUT_NAMES[0]).touch()
    with pytest.raises(FileExistsError, match="never overwritten"):
        build_showcase_sample._require_unused_outputs(tmp_path)


def _mock_sample_generation(monkeypatch, *, sensitive=False, before_export=None):
    quality = {"approval_gate": {"passed": True}}
    analysis = {
        "knowledge": {
            "status": "ready",
            "retrieved_chunks": [{"chunk_id": "fixture"}],
            "index_manifest_sha256": "a" * 64,
        }
    }
    row = {
        "governed_gate_passed": True,
        "rag_behavior_passed": True,
        "knowledge_status": "ready",
        "retrieved_chunks": 1,
    }
    snapshot = _recorded_synthetic_snapshot(analysis)
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        for suffix in (".md", ".pdf", ".docx"):
            archive.writestr(f"reports/synthetic{suffix}", b"synthetic export fixture")
        audit_record = {"sensitive_payload": {"fixture": True}} if sensitive else {}
        archive.writestr("governance/audit_record.json", json.dumps(audit_record))

    def export(*args, **kwargs):
        if before_export is not None:
            before_export()
        return {"content": archive_bytes.getvalue()}

    monkeypatch.setattr(build_showcase_sample, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(build_showcase_sample, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(
        build_showcase_sample,
        "run_scenario_with_artifacts",
        lambda _: {"row": row, "analysis": analysis, "report": "Synthetic draft", "model_evidence": snapshot},
    )
    monkeypatch.setattr(build_showcase_sample, "evaluate_governed_report", lambda *args: quality)
    monkeypatch.setattr(build_showcase_sample, "evaluate_report_grounding", lambda *args: {})
    monkeypatch.setattr(build_showcase_sample, "build_export_register_snapshot", lambda: {})
    monkeypatch.setattr(build_showcase_sample, "save_report_audit", lambda _: "unused-test-audit.json")
    monkeypatch.setattr(build_showcase_sample, "create_pilot_export_package", export)


def test_showcase_validates_privacy_before_writing_any_files(tmp_path, monkeypatch):
    _mock_sample_generation(monkeypatch, sensitive=True)
    with pytest.raises(RuntimeError, match="sensitive audit payload"):
        build_showcase_sample.build_showcase_sample(tmp_path)
    assert not any(tmp_path.iterdir())


def test_showcase_preserves_output_created_during_generation(tmp_path, monkeypatch):
    existing = tmp_path / build_showcase_sample._OUTPUT_NAMES[-1]
    _mock_sample_generation(monkeypatch, before_export=lambda: existing.write_bytes(b"other evidence"))
    with pytest.raises(FileExistsError, match="never overwritten"):
        build_showcase_sample.build_showcase_sample(tmp_path)
    assert existing.read_bytes() == b"other evidence"
    assert list(tmp_path.iterdir()) == [existing]


def test_showcase_writes_new_outputs_without_replacing_previous_evidence(tmp_path, monkeypatch):
    _mock_sample_generation(monkeypatch)
    result = build_showcase_sample.build_showcase_sample(tmp_path)
    assert set(result["files"]) == set(build_showcase_sample._OUTPUT_NAMES)
    assert {path.name for path in tmp_path.iterdir()} == set(build_showcase_sample._OUTPUT_NAMES)


def test_showcase_rejects_external_model_before_generation(tmp_path, monkeypatch):
    called = False

    def run_scenario(_scenario):
        nonlocal called
        called = True
        raise AssertionError("generation must not start")

    monkeypatch.setattr(build_showcase_sample, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(build_showcase_sample, "MODEL_ENDPOINT_IS_LOCAL", False)
    monkeypatch.setattr(build_showcase_sample, "run_scenario_with_artifacts", run_scenario)

    with pytest.raises(RuntimeError, match="local loopback"):
        build_showcase_sample.build_showcase_sample(tmp_path)

    assert called is False


@pytest.mark.parametrize(
    ("row_updates", "knowledge_updates"),
    (
        ({"rag_behavior_passed": False}, {}),
        ({"knowledge_status": "disabled"}, {"status": "disabled"}),
        ({"retrieved_chunks": 0}, {"retrieved_chunks": []}),
        ({}, {"index_manifest_sha256": None}),
    ),
)
def test_showcase_rejects_degraded_or_unbound_rag_before_export(
    tmp_path,
    monkeypatch,
    row_updates,
    knowledge_updates,
):
    row = {
        "governed_gate_passed": True,
        "blocking_failures": [],
        "rag_behavior_passed": True,
        "knowledge_status": "ready",
        "retrieved_chunks": 1,
    }
    row.update(row_updates)
    knowledge = {
        "status": "ready",
        "retrieved_chunks": [{"chunk_id": "one"}],
        "index_manifest_sha256": "a" * 64,
    }
    knowledge.update(knowledge_updates)
    monkeypatch.setattr(build_showcase_sample, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(build_showcase_sample, "MODEL_ENDPOINT_IS_LOCAL", True)
    monkeypatch.setattr(
        build_showcase_sample,
        "run_scenario_with_artifacts",
        lambda _scenario: {"row": row, "analysis": {"knowledge": knowledge}, "report": "unused"},
    )

    with pytest.raises(RuntimeError, match="requires verified ready RAG"):
        build_showcase_sample.build_showcase_sample(tmp_path)

    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_showcase_cli_defaults_to_project_release_directory(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")
    captured = {}

    def build(output_dir, *, example_name):
        captured.update(output_dir=output_dir, example_name=example_name)
        return {"built": True}

    monkeypatch.setattr(build_showcase_sample, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build_showcase_sample, "build_showcase_sample", build)

    assert build_showcase_sample.main([]) == 0
    assert captured == {
        "output_dir": tmp_path / "examples/v0.6.0",
        "example_name": build_showcase_sample.DEFAULT_EXAMPLE,
    }
    assert '"built": true' in capsys.readouterr().out.lower()


def test_showcase_cli_rejects_release_directory_escape(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")
    monkeypatch.setattr(build_showcase_sample, "PROJECT_ROOT", tmp_path)

    with pytest.raises(SystemExit) as caught:
        build_showcase_sample.main(["--release-dir", "../outside"])

    assert caught.value.code == 2
