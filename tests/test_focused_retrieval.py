"""Bounded, source-independent focused retrieval and failure contracts."""

import copy
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.agents.official_knowledge_agent import OfficialKnowledgeAgent, build_focus_queries
from src.rag import service as module
from src.rag.errors import RagError


def _doc(text, number=1, source=None, title="Synthetic reference"):
    return {
        "source_id": source or f"synthetic-{number}",
        "chunk_id": f"chunk-{number}",
        "title": title,
        "text": text,
        "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "jurisdictions": ["Australia"],
        "score": 0.95,
    }


@pytest.fixture
def harness(monkeypatch):
    settings = SimpleNamespace(
        top_k=2,
        candidate_multiplier=4,
        score_threshold=0.2,
        dense_weight=0.5,
        lexical_coverage_threshold=0.61,
        semantic_score_threshold=0.7,
        semantic_coverage_threshold=0.2,
        rrf_k=60,
        max_chunks_per_source=1,
    )
    state = {"locked": False, "batches": [], "queries": 0, "documents": [], "drift": False, "manifests": 0}
    manifest = {
        "schema": "synthetic-index",
        "embedding_model": "synthetic",
        "embedding_provider": "fastembed",
        "embedding_identity": {"id": "synthetic"},
        "embedding_dimension": 2,
        "source_count": 1,
        "chunk_count": 20,
        "manifest_sha256": "a" * 64,
        "documents_artifact": {"sha256": "b" * 64},
        "built_at_utc": "2026-09-12T00:00:00Z",
    }

    @contextmanager
    def locked(_):
        assert not state["locked"]
        state["locked"] = True
        try:
            yield
        finally:
            state["locked"] = False

    def load(*args, **kwargs):
        assert state["locked"]
        state["manifests"] += 1
        return {**manifest, "manifest_sha256": "c" * 64 if state["drift"] and state["manifests"] > 1 else "a" * 64}

    def embed(settings, embedder, texts, identity):
        assert state["locked"] and identity == manifest["embedding_identity"]
        state["batches"].append(list(texts))
        if state.get("embedding_error"):
            raise RagError("rag_embedding_unavailable", "Synthetic provider failure.")
        return state.get("vectors", [[1.0, 0.0] for _ in texts])

    monkeypatch.setattr(module, "index_read_write_lock", locked)
    monkeypatch.setattr(module, "_configuration_unready_status", lambda _: None)
    monkeypatch.setattr(module, "_unready_index_status", lambda _: None)
    monkeypatch.setattr(module, "load_and_validate_index", load)
    monkeypatch.setattr(module, "index_snapshot", lambda settings, value: {"manifest": value["manifest_sha256"]})
    monkeypatch.setattr(module, "load_index_documents", lambda *args: copy.deepcopy(state["documents"]))
    monkeypatch.setattr(module, "embed_with_identity", embed)
    service = module.RagService(settings=settings, embedder=object())

    def query(vector, **kwargs):
        assert state["locked"]
        state["queries"] += 1
        if state.get("query_error"):
            raise RagError("rag_query_failed", "Synthetic query failure.")
        return copy.deepcopy(state["documents"])

    monkeypatch.setattr(service, "_query_index", query)
    return service, state


@pytest.mark.parametrize(
    "original,focus",
    [
        ("Which evacuation route is safe now?", "Bushfire emergency kit"),
        ("Static planning reference", "Give the current fire warning"),
        ("Guarantee this shelter is safe", "Static emergency kit"),
    ],
)
def test_all_queries_are_safety_checked_before_index_or_embedding(harness, original, focus):
    service, state = harness
    result = service.retrieve_planning(original, focus_queries=[{"focus_id": "kits", "query": focus}])
    assert result["status"] == "out_of_scope" and result["retrieved_chunks"] == []
    assert state["batches"] == [] and state["manifests"] == 0


def test_focus_plan_uses_only_bounded_canonical_vocabulary():
    concerns = ["Communication channels", "Evacuation", "Emergency kit", "Pets", "Road disruption", "PRIVATE_SENTINEL"]
    plan = build_focus_queries(concerns)
    assert len(plan) == 4 and all(len(row["query"]) <= 256 for row in plan)
    assert "warning channel" in plan[0]["query"]
    assert "PRIVATE_SENTINEL" not in str(plan)
    assert build_focus_queries(["not a known concern"]) == []


def test_one_batched_embedding_and_one_locked_snapshot_for_whole_plan(harness):
    service, state = harness
    focuses = [{"focus_id": f"focus_{i}", "query": f"Bushfire kit topic {i}"} for i in range(4)]
    result = service.retrieve_planning("Orbital mechanics", focus_queries=focuses)
    assert result["status"] == "no_match"
    assert len(state["batches"]) == 1 and len(state["batches"][0]) == 5
    assert state["queries"] == 5 and state["manifests"] == 2 and not state["locked"]
    assert result["retrieval_configuration"]["query_plan"]["fusion"] == module.PLANNING_FUSION


@pytest.mark.parametrize(
    "text,title",
    [
        ("Official bushfire emergency source information.", "Synthetic reference"),
        ("Bushfire planning and emergency information.", "Emergency kit"),
    ],
)
def test_generic_domain_words_and_title_only_focus_do_not_admit_evidence(harness, text, title):
    service, state = harness
    state["documents"] = [_doc(text, title=title)]
    result = service.retrieve_planning(
        "Orbital mechanics", focus_queries=[{"focus_id": "kits", "query": "Bushfire emergency kit"}]
    )
    assert result["status"] == "no_match" and result["retrieved_chunks"] == []


def test_meaningful_body_focus_can_add_evidence_and_keeps_jurisdiction(harness):
    service, state = harness
    state["documents"] = [_doc("Emergency kit medicines and documents."), _doc("Emergency kit details.", 2)]
    state["documents"][1]["jurisdictions"] = ["Queensland"]
    result = service.retrieve_planning(
        "Orbital mechanics",
        jurisdiction="Tasmania",
        focus_queries=[{"focus_id": "kits", "query": "Bushfire emergency kit"}],
    )
    assert [row["chunk_id"] for row in result["retrieved_chunks"]] == ["chunk-1"]
    assert result["retrieved_chunks"][0]["selection_origin"] == "focus_supplement"


def test_focus_filter_happens_before_final_top_k_and_source_cap(harness, monkeypatch):
    service, state = harness
    service.settings.top_k = 1
    irrelevant = _doc("Emergency source information.", 1, source="shared")
    relevant = _doc("Emergency kit supplies.", 2, source="shared")
    state["documents"] = [irrelevant, relevant]
    observed = []

    def rank(query, documents, dense, **kwargs):
        observed.append(kwargs)
        return [] if query == "Orbital mechanics" else [irrelevant, relevant][: kwargs["top_k"]]

    monkeypatch.setattr(module, "hybrid_rank", rank)
    result = service.retrieve_planning(
        "Orbital mechanics", focus_queries=[{"focus_id": "kits", "query": "Bushfire emergency kit"}]
    )
    assert observed[0]["top_k"] == 1 and observed[1]["top_k"] == 4
    assert observed[1]["max_chunks_per_source"] == 4
    assert [row["chunk_id"] for row in result["retrieved_chunks"]] == ["chunk-2"]


def test_base_candidates_survive_many_focus_votes_and_supplements_use_remaining_capacity():
    settings = SimpleNamespace(rrf_k=60, max_chunks_per_source=1)
    base = _doc("Base evidence.", 1, source="shared")
    challenger = _doc("Repeatedly matched focus evidence.", 2, source="shared")
    supplement = _doc("Another source.", 3)
    plan = [
        {"focus_id": None, "query": "base"},
        {"focus_id": "one", "query": "one"},
        {"focus_id": "two", "query": "two"},
    ]
    result = module._fuse_planning_results(
        plan, [[base], [challenger, supplement], [challenger, supplement]], settings, 2
    )
    assert [row["chunk_id"] for row in result] == ["chunk-1", "chunk-3"]
    assert result[0]["base_query_rank"] == 1 and result[1]["base_query_rank"] is None
    assert len(module._fuse_planning_results(plan, [[base], [challenger], [challenger]], settings, 1)) == 1


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[1.0, 0.0]], [[True, 0], [1, 0]], [[float("nan"), 0], [1, 0]], None])
def test_invalid_embedding_batch_fails_closed_before_queries(harness, vectors):
    service, state = harness
    state["vectors"] = vectors
    result = service.retrieve_planning(
        "Orbital mechanics", focus_queries=[{"focus_id": "kits", "query": "Emergency kit"}]
    )
    assert result["status"] == "unavailable" and result["error_code"] == "rag_embedding_invalid"
    assert result["retrieved_chunks"] == [] and state["queries"] == 0


@pytest.mark.parametrize("failure", ["drift", "embedding_error", "query_error"])
def test_whole_plan_fails_closed_on_identity_change_or_partial_failure(harness, failure):
    service, state = harness
    state[failure] = True
    state["documents"] = [_doc("Emergency kit planning.")]
    result = service.retrieve_planning(
        "Orbital mechanics", focus_queries=[{"focus_id": "kits", "query": "Emergency kit"}]
    )
    assert result["status"] == "unavailable" and result["retrieved_chunks"] == []
    assert not state["locked"]


@pytest.mark.parametrize("top_k", [0, -1, True, 1.2])
def test_invalid_top_k_is_rejected_before_io(harness, top_k):
    service, state = harness
    with pytest.raises(ValueError, match="positive integer"):
        service.retrieve_planning("planning", top_k=top_k)
    assert state["batches"] == []


def test_duplicate_queries_are_deduplicated_and_duplicate_focus_ids_rejected(harness):
    service, state = harness
    result = service.retrieve_planning(
        "base",
        focus_queries=[
            {"focus_id": "a", "query": "base"},
            {"focus_id": "b", "query": "kit"},
            {"focus_id": "c", "query": "kit"},
        ],
    )
    assert result["status"] == "no_match" and state["batches"] == [["base", "kit"]]
    with pytest.raises(ValueError, match="unique"):
        service.retrieve_planning(
            "base", focus_queries=[{"focus_id": "a", "query": "kit"}, {"focus_id": "a", "query": "route"}]
        )


def test_legacy_service_still_receives_original_api_only():
    class Legacy:
        def retrieve(self, query, **kwargs):
            assert kwargs == {"jurisdiction": "Tasmania", "trusted_planning_scope": True}
            return {"status": "no_match", "retrieved_chunks": []}

    result = OfficialKnowledgeAgent(service=Legacy()).run({"state": "Tasmania"}, "school", ["Evacuation"], "7 days")
    assert result["query_components"]["concerns"] == ["Evacuation"]
