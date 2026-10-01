import builtins
import copy
import json

import pytest

from scripts import citation_criteria_comparison as comparison


@pytest.fixture(scope="module")
def fixed_sources():
    # Read fixed Git blobs, not any prepared or closed campaign artifact.
    return {commit: comparison._git_sources(commit) for commit in (comparison.BASELINE, comparison.CANDIDATE)}


@pytest.fixture
def bundle(monkeypatch, fixed_sources):
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(fixed_sources[commit]))
    return comparison.prepare_bundle()


def test_complete_fixed_builders_change_only_prompt_and_do_not_mutate_inputs(bundle, fixed_sources):
    from src.model_evidence import json_sha256, validate_recorded_assembly
    from src.source_attribution import format_rag_citation_token

    assert bundle["source_identity"]["changed_source_paths"] == ["src/report_template.py"]
    assert len(bundle["cases"]) == 3 and bundle["execution_plan"]["max_requests"] == 6
    assert bundle["execution_plan"]["parameters"] == comparison.PARAMETERS
    assert bundle["observations"]["model_calls"] == 0 and bundle["observations"]["semantic_accuracy"] is None
    assert bundle["production_enabled"] is False and bundle["release_gate"] == "inactive"
    assert [case["raw_inputs"] for case in bundle["cases"]] == [
        case["raw_inputs"] for case in comparison._synthetic_cases()
    ]
    for case in bundle["cases"]:
        first, second = case["arms"]["baseline"], case["arms"]["candidate"]
        assert first["analysis"] == second["analysis"]
        assert first["analysis_sha256"] == second["analysis_sha256"] == json_sha256(first["analysis"])
        assert first["prompt_context_sha256"] == second["prompt_context_sha256"]
        assert first["raw_inputs_sha256"] == second["raw_inputs_sha256"] == case["raw_inputs_sha256"]
        assert first["shared_rag_sha256"] == second["shared_rag_sha256"] == case["shared_rag_sha256"]
        assert first["prompt"] != second["prompt"] and "Provide criteria only" in first["prompt"]
        assert "Section 9 needs passage support for established criteria" in second["prompt"]
        for arm, commit in (("baseline", comparison.BASELINE), ("candidate", comparison.CANDIDATE)):
            agent, builder = comparison._arm_builders(fixed_sources[commit], commit)
            assert builder.__code__.co_filename == f"git:{commit}:src/report_template.py"
            assert agent.run.__code__.co_filename == f"git:{commit}:src/agents/report_agent.py"
            current = case["arms"][arm]
            assert current["visibility_status"] == "planned_not_submitted"
            assert current["prompt"].count(case["shared_rag"]["context"]) == 1
            assert (
                validate_recorded_assembly(case["shared_rag"], current["analysis"])
                == case["shared_rag"]["visible_chunks"]
            )
            for chunk in case["raw_inputs"]["knowledge"]["retrieved_chunks"]:
                assert current["prompt"].count(chunk["text"]) == 1
                assert format_rag_citation_token(chunk) in current["prompt"]
            assert all(item["question"] not in current["prompt"] for item in case["review"]["items"])


def test_exact_cases_and_nineteen_unfilled_review_dimensions(bundle):
    assert [len(case["review"]["items"]) for case in bundle["cases"]] == [6, 6, 7]
    passages = [case["raw_inputs"]["knowledge"]["retrieved_chunks"][0]["text"] for case in bundle["cases"]]
    assert "27 blank communication-contact worksheet templates" in passages[0] and "2016 and 2019" in passages[0]
    assert "L-31 as received on 6 February 2025" in passages[1] and "receiving clerk's initials" in passages[1]
    for qualifier in (
        "only if",
        "unless it is marked withdrawn",
        "A withdrawn file is not eligible for documentary audit.",
        "dated accession sheet",
        "countersigned",
        "does not apply to withdrawn files",
    ):
        assert qualifier in passages[2]
    for case in bundle["cases"]:
        raw = case["raw_inputs"]
        assert raw["community"] == {} and raw["data"]["sources"] == []
        assert raw["risk_context"] == {"risk_points": [], "assumptions": []}
        assert "No prior narrative evidence" not in json.dumps(raw)
        assert set(case["review"]["states"]) == {
            "supported",
            "partial_or_scope_changed",
            "insufficient",
            "not_generated_or_unassessable",
        }
        for item in case["review"]["items"]:
            assert all(value is None for judgment in item["by_arm"].values() for value in judgment.values())


def test_prepare_is_pure_no_dotenv_sdk_config_retrieval_or_old_campaign(monkeypatch, fixed_sources):
    import dotenv
    import openai

    from scripts import scoped_basis_comparison as old
    from src.rag import service

    def forbidden(*args, **kwargs):
        pytest.fail("Preparation must not invoke environment, SDK, retrieval or an old preparation")

    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(old, "prepare_bundle", forbidden)
    monkeypatch.setattr(old, "_arm_builders", forbidden)
    monkeypatch.setattr(service.RagService, "__init__", forbidden)
    monkeypatch.setattr(service.RagService, "retrieve", forbidden)
    monkeypatch.setattr(service.RagService, "retrieve_planning", forbidden)
    original_import = builtins.__import__

    def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name not in {"src.config", "src.model_runtime"}
        assert not (name == "src" and {"config", "model_runtime"}.intersection(fromlist))
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(fixed_sources[commit]))
    first = comparison.prepare_bundle()
    assert first == comparison.prepare_bundle()


@pytest.mark.parametrize(
    "target",
    ["src/report_template.py", "src/report_basis.py", "src/rag/context.py", "scripts/run_scoped_basis_comparison.py"],
)
def test_actual_source_and_helper_drift_rejected(monkeypatch, fixed_sources, target):
    original = comparison._working_bytes
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(fixed_sources[commit]))
    monkeypatch.setattr(
        comparison, "_working_bytes", lambda path: original(path) + b"\n# changed" if path == target else original(path)
    )
    with pytest.raises(comparison.ComparisonBlocked, match="source_drift|shared_helper_drift"):
        comparison.prepare_bundle()


def test_cross_git_helper_change_rejected(monkeypatch, fixed_sources):
    altered = copy.deepcopy(fixed_sources)
    altered[comparison.BASELINE]["src/report_basis.py"] += b"\n# changed"
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: altered[commit])
    with pytest.raises(comparison.ComparisonBlocked, match="unexpected_git_source_change"):
        comparison.prepare_bundle()


@pytest.mark.parametrize(
    "mutation", ["prompt", "rubric", "raw", "assembly", "identity", "parameters", "order", "stop", "numeric_type"]
)
def test_rebuild_rejects_tamper_even_with_new_external_hash(bundle, monkeypatch, tmp_path, mutation):
    changed = copy.deepcopy(bundle)
    case = changed["cases"][0]
    if mutation == "prompt":
        case["arms"]["baseline"]["prompt"] += " injected"
        case["arms"]["baseline"]["prompt_sha256"] = comparison._sha(case["arms"]["baseline"]["prompt"].encode())
    elif mutation == "rubric":
        case["review"]["items"][0]["question"] = "changed"
    elif mutation == "raw":
        case["raw_inputs"]["plan"]["planning_priorities"] = ["changed"]
    elif mutation == "assembly":
        case["shared_rag"]["context"] += " changed"
    elif mutation == "identity":
        changed["source_identity"]["candidate_commit"] = comparison.BASELINE
    elif mutation == "parameters":
        changed["execution_plan"]["parameters"]["top_p"] = 0.9
    elif mutation == "order":
        changed["execution_plan"]["request_order"].reverse()
    elif mutation == "stop":
        changed["execution_plan"]["stop_on_first_request_failure"] = False
    else:
        changed["execution_plan"]["max_requests"] = 6.0
    path = tmp_path / "prepared.json"
    content = comparison._json_bytes(changed)
    path.write_bytes(content)
    monkeypatch.setattr(comparison, "_prepared_path", lambda: path)
    with pytest.raises(comparison.ComparisonBlocked, match="prepared_content_or_source_drift"):
        comparison.validate_prepared(comparison._sha(content))


def test_cli_utf8_exclusive_fixed_path_and_readonly_validation(bundle, monkeypatch, tmp_path):
    path = tmp_path / "output" / comparison.CAMPAIGN / "prepared.json"
    monkeypatch.setattr(comparison, "prepare_bundle", lambda: copy.deepcopy(bundle))
    monkeypatch.setattr(comparison, "_prepared_path", lambda: path)
    assert comparison.main(["prepare"]) == 0
    original = path.read_bytes()
    assert json.loads(original.decode("utf-8")) == bundle
    assert comparison.main(["validate", "--expected-prepared-file-sha256", comparison._sha(original)]) == 0
    for argv in (["prepare"], ["run"], ["prepare", "--output", "other.json"]):
        with pytest.raises(SystemExit) as error:
            comparison.main(argv)
        assert error.value.code == 2
    assert path.read_bytes() == original
    assert sorted(item.name for item in path.parent.iterdir()) == ["prepared.json"]
