import pytest

from scripts import build_showcase_sample


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
