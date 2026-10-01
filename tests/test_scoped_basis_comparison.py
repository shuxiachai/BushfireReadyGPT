import builtins
import copy
import hashlib
import json
import sys

import pytest

from scripts import scoped_basis_comparison as comparison
from tests.scoped_basis_fixtures import (
    REAL_PROJECT_ROOT,
    fixed_git_sources,
    historical_checkout,
    verify_real_shared_helpers,
)


@pytest.fixture
def frozen_sources(monkeypatch, tmp_path):
    """Explicit historical test checkout, not current production admission."""
    with historical_checkout(monkeypatch, tmp_path) as sources:
        yield sources


@pytest.fixture
def fixed_sources(monkeypatch, frozen_sources):
    # Keep the unchanged guards on reference files, with cached fixed Git blobs.
    trees = dict(zip((comparison.BASELINE, comparison.CANDIDATE), frozen_sources[1:]))
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(trees[commit]))


@pytest.fixture
def bundle(fixed_sources):
    return comparison.prepare_bundle()


def test_prepare_is_offline_and_leaves_raw_inputs_and_production_modules_unchanged(monkeypatch, fixed_sources):
    from src.agents import pipeline
    from src.rag import context, service
    from src.rag import index as rag_index

    def forbidden(*args, **kwargs):
        pytest.fail("Offline preparation must not run a pipeline, retrieve, index, load dotenv or construct an SDK")

    monkeypatch.setattr(pipeline, "run_analysis_pipeline", forbidden)
    monkeypatch.setattr(service.RagService, "__init__", forbidden)
    monkeypatch.setattr(service.RagService, "retrieve", forbidden)
    monkeypatch.setattr(rag_index, "load_and_validate_index", forbidden)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"dotenv", "src.config", "openai"} or name.startswith(
            ("scripts.evaluate_", "scripts.section_scope_comparison")
        ):
            forbidden()
        return original_import(name, *args, **kwargs)

    raw_cases = comparison._synthetic_cases()
    before = copy.deepcopy(raw_cases)
    assembly_calls = []
    actual_assembly = context.assemble_planning_context

    def tracked_assembly(*args, **kwargs):
        assembly_calls.append((copy.deepcopy(args), copy.deepcopy(kwargs)))
        return actual_assembly(*args, **kwargs)

    monkeypatch.setattr(context, "assemble_planning_context", tracked_assembly)
    monkeypatch.setattr(comparison, "_synthetic_cases", lambda: raw_cases)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    protected = {key: value for key, value in sys.modules.items() if key.startswith("src.")}
    prepared = comparison.prepare_bundle()
    assert len(assembly_calls) == 3
    assert raw_cases == before
    assert all(sys.modules[key] is value for key, value in protected.items())
    assert prepared["observations"]["model_calls"] == 0
    assert prepared["observations"]["semantic_accuracy"] is None
    assert prepared["production_enabled"] is False
    assert prepared["release_gate"] == "inactive"


def test_git_commands_only_read_full_fixed_commits_and_do_not_bind_head(monkeypatch):
    commands = []
    actual_git = comparison._git

    def tracked(*args, **kwargs):
        commands.append(args)
        if args == ("cat-file", "--batch"):
            assert all(len(line) == 40 for line in kwargs["input_data"].splitlines())
        return actual_git(*args, **kwargs)

    monkeypatch.setattr(comparison, "_git", tracked)
    comparison._git_sources(comparison.BASELINE)
    comparison._git_sources(comparison.CANDIDATE)
    assert commands == [
        command
        for commit in (comparison.BASELINE, comparison.CANDIDATE)
        for command in (
            ("rev-parse", "--verify", f"{commit}^{{commit}}"),
            ("ls-tree", "-r", "-z", commit, "--", "src"),
            ("cat-file", "--batch"),
        )
    ]


def test_fixed_sources_are_exact_git_blobs_without_archive_newline_conversion(monkeypatch, frozen_sources):
    with monkeypatch.context() as current:
        current.setattr(comparison, "PROJECT_ROOT", REAL_PROJECT_ROOT)
        source = comparison._git("show", f"{comparison.CANDIDATE}:src/abs_indicators.py")
    assert frozen_sources[2]["src/abs_indicators.py"] == source
    assert (
        frozen_sources[0]["git_python_source_sha256"]["candidate"]["src/abs_indicators.py"]
        == hashlib.sha256(source).hexdigest()
    )


def test_both_complete_builders_and_candidate_basis_are_bound_to_git(bundle):
    from src.model_evidence import json_sha256, text_sha256, validate_recorded_assembly
    from src.source_attribution import format_rag_citation_token

    identity = bundle["source_identity"]
    assert identity["baseline_commit"] == comparison.BASELINE
    assert identity["candidate_commit"] == comparison.CANDIDATE
    assert set(identity["changed_source_paths"]) == comparison.ALLOWED_SOURCE_CHANGES
    assert "src/report_basis.py" not in identity["git_python_source_sha256"]["baseline"]
    assert "src/report_basis.py" in identity["git_python_source_sha256"]["candidate"]
    for path in (
        "src/abs_indicators.py",
        "src/evidence_confidence.py",
        "src/focus_coverage.py",
        "src/governance.py",
        "src/source_attribution.py",
        "src/evidence_formatting.py",
        "src/agents/profile_agent.py",
        "src/agents/planner_agent.py",
        "src/rag/service.py",
        "src/rag/context.py",
        "src/rag/lexical.py",
        "src/model_evidence.py",
    ):
        assert (
            identity["git_python_source_sha256"]["baseline"][path]
            == identity["git_python_source_sha256"]["candidate"][path]
        )
    assert len(bundle["cases"]) == 3
    for case in bundle["cases"]:
        baseline, candidate = case["arms"]["baseline"], case["arms"]["candidate"]
        assert "Risk Context Agent:\n" in baseline["analysis"]["prompt_context"]
        assert "Planner Agent:\n" in baseline["analysis"]["prompt_context"]
        assert "R3 rule-derived planning cues" in candidate["analysis"]["prompt_context"]
        assert "<BEGIN_COMMUNITY_P2_BASIS_DATA>" not in baseline["prompt"]
        assert candidate["prompt"].count("<BEGIN_COMMUNITY_P2_BASIS_DATA>") == 1
        assert baseline["prompt_context_sha256"] != candidate["prompt_context_sha256"]
        assert baseline["analysis_sha256"] != candidate["analysis_sha256"]
        assert baseline["source_tokens"] == candidate["source_tokens"]
        assert baseline["raw_inputs_sha256"] == candidate["raw_inputs_sha256"] == json_sha256(case["raw_inputs"])
        assert baseline["shared_rag_sha256"] == candidate["shared_rag_sha256"] == json_sha256(case["shared_rag"])
        assert case["shared_rag"]["manifest"]["schema"] == "rag-context-assembly-v2"
        assert case["shared_rag"]["manifest"]["max_characters"] == 8000
        for arm in case["arms"].values():
            assert arm["prompt"].count(case["shared_rag"]["context"]) == 1
            assert arm["analysis"]["rag_context_assembly"] == case["shared_rag"]
            assert (
                validate_recorded_assembly(case["shared_rag"], arm["analysis"]) == case["shared_rag"]["visible_chunks"]
            )
            assert arm["analysis_sha256"] == json_sha256(arm["analysis"])
            assert arm["prompt_sha256"] == text_sha256(arm["prompt"])
            assert arm["visibility_status"] == "planned_not_submitted"
            for chunk in case["raw_inputs"]["knowledge"]["retrieved_chunks"]:
                assert arm["prompt"].count(chunk["text"]) == 1
                assert format_rag_citation_token(chunk) in arm["prompt"]
                assert chunk["source_id"].startswith("synthetic-")
                assert chunk["synthetic_development"] is True
        assert case["raw_inputs"]["data"]["sources"] == []


def test_periods_denominators_unknowns_and_original_conflict_are_visible_without_rubric_leakage(bundle):
    case = bundle["cases"][1]
    prompt = case["arms"]["candidate"]["prompt"]
    assert "2021 fictional household/resident tables; 2023 synthetic population estimate" in prompt
    assert "Older people: percent of residents. No-car: percent of households." in prompt
    assert '"language_other_than_english_pct":null' in prompt
    assert '"matched_sa2_count":2' in prompt
    assert "high language-support label is a synthetic rule priority" in prompt
    for case in bundle["cases"]:
        for item in case["review"]["items"]:
            for arm in case["arms"].values():
                assert item["id"] not in arm["prompt"]
                assert item["question"] not in arm["prompt"]
            for judgment in item["by_arm"].values():
                assert judgment == {"state": None, "output_span": None, "submitted_evidence_span": None, "reason": None}
        assert case["review"]["allowed_states"] == list(comparison.REVIEW_STATES)
    for arm in bundle["cases"][2]["arms"].values():
        assert "Routine property maintenance increases building defects" in arm["prompt"]
        assert "describes the same maintenance as reducing building defects" in arm["prompt"]
        assert "records an external wall-panel gap and a maintenance request" in arm["prompt"]


def test_empty_assembly_and_unknown_basis_are_valid(frozen_sources):
    from src.rag.context import assemble_planning_context

    raw = comparison._synthetic_cases()[0]["raw_inputs"]
    raw["knowledge"]["retrieved_chunks"] = []
    assembly = assemble_planning_context(raw["knowledge"])
    for arm, sources in zip(("baseline", "candidate"), frozen_sources[1:]):
        result = comparison._build_arm(raw, assembly, comparison._arm_builders(sources, arm))
        assert result["prompt"].count(assembly["context"]) == 1
    assert '"population":null' in result["prompt"]


def test_new_cases_cover_scoped_planning_without_prefilling_dimension_judgments(bundle):
    household, population, maintenance = bundle["cases"]
    first = household["raw_inputs"]["knowledge"]["retrieved_chunks"][0]["text"]
    assert "households that have recorded a member's support needs" in first
    assert "evacuation planning record lists the nominated support contact" in first
    assert "does not establish a campus" not in first
    assert "garden sheds" not in first
    assert "18 preparedness contact forms" in population["raw_inputs"]["knowledge"]["retrieved_chunks"][0]["text"]
    assert "Completion status is unrecorded" in maintenance["raw_inputs"]["knowledge"]["retrieved_chunks"][1]["text"]
    assert "evacuation support needs" in household["raw_inputs"]["plan"]["planning_priorities"][0]
    assert "population profile" in population["raw_inputs"]["plan"]["planning_priorities"][0]
    assert "qualification and exercise records" in maintenance["raw_inputs"]["plan"]["planning_priorities"][0]
    for case in bundle["cases"]:
        review = case["review"]
        dimensions = {item["id"]: item["question"] for item in review["items"]}
        assert "supporting" not in dimensions["rubric_citation_presence"]
        assert "valid source bindings" in dimensions["rubric_citation_presence"]
        assert "rubric_source_support" in dimensions and "rubric_applicability" in dimensions
        assert "one dimension, not overall claim correctness or accuracy" in review["state_scope"]
        assert "Every future judgment requires a reason" in review["span_requirement"]
        assert "output_span may be null" in review["span_requirement"]


def test_plan_is_only_six_interleaved_initial_requests_with_no_observed_results(bundle):
    plan = bundle["execution_plan"]
    assert plan["status"] == "planned"
    assert plan["max_requests"] == 6 and plan["attempts_per_case_arm"] == 1
    assert [row["arm"] for row in plan["request_order"]] == [
        "baseline",
        "candidate",
        "candidate",
        "baseline",
        "baseline",
        "candidate",
    ]
    assert plan["parameters"] == {
        "temperature": 0.2,
        "max_output_tokens": 2300,
        "thinking": "disabled",
        "sdk_retries": 0,
    }
    assert plan["structural_repair"] is plan["revision"] is plan["model_judge"] is False
    assert plan["stop_on_first_request_failure"] is True
    assert plan["replacement_requests"] is False
    assert plan["failure_types"] == ["length", "protocol", "timeout", "transport"]
    assert all(value is None for key, value in bundle["observations"].items() if key not in {"status", "model_calls"})


@pytest.mark.parametrize("path", ["src/rag/lexical.py", "src/abs_indicators.py", "src/agents/profile_agent.py"])
def test_changed_shared_git_helper_is_rejected(monkeypatch, frozen_sources, path):
    trees = dict(zip((comparison.BASELINE, comparison.CANDIDATE), copy.deepcopy(frozen_sources[1:])))
    trees[comparison.BASELINE][path] += b"\n# helper drift\n"
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: trees[commit])
    with pytest.raises(comparison.ComparisonBlocked, match="unexpected_git_source_change"):
        comparison.prepare_bundle()


@pytest.mark.parametrize(
    "path", ["src/report_basis.py", "src/report_template.py", "src/agents/report_agent.py", "src/rag/service.py"]
)
def test_current_source_drift_is_rejected(monkeypatch, fixed_sources, path):
    actual = comparison._working_bytes
    monkeypatch.setattr(
        comparison, "_working_bytes", lambda name: actual(name) + (b"\n# drift\n" if name == path else b"")
    )
    with pytest.raises(comparison.ComparisonBlocked, match="current_source_drift"):
        comparison.prepare_bundle()


def _write_test_bundle(root, value):
    path = root / "output" / comparison.CAMPAIGN / "prepared.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_fixture_validation_rebuilds_fixed_sources_and_all_case_fields(monkeypatch, tmp_path, bundle):
    path, digest = _write_test_bundle(tmp_path, bundle)
    monkeypatch.setattr(comparison, "_prepared_path", lambda: path)
    assert comparison.validate_prepared(digest) == bundle
    assert comparison.prepare_bundle() == bundle
    changed = copy.deepcopy(bundle)
    changed["cases"][1]["review"]["items"][0]["question"] = "Changed review dimension"
    _, new_digest = _write_test_bundle(tmp_path, changed)
    with pytest.raises(comparison.ComparisonBlocked, match="prepared_content_or_source_drift"):
        comparison.validate_prepared(new_digest)


def test_real_checkout_rejects_current_template_drift_without_historical_fixture():
    assert comparison.PROJECT_ROOT.resolve() == REAL_PROJECT_ROOT.resolve()
    for operation in (comparison._source_snapshot, comparison.prepare_bundle):
        with pytest.raises(comparison.ComparisonBlocked, match="^current_source_drift:src/report_template.py$"):
            operation()


@pytest.mark.parametrize("mutation", ["shared_helper", "extractor_body", "missing_callee", "governance_value"])
def test_historical_fixture_rejects_changes_to_actual_shared_dependencies(mutation):
    candidate = dict(fixed_git_sources()[comparison.CANDIDATE])
    verify_real_shared_helpers(candidate)
    if mutation == "shared_helper":
        candidate["src/rag/lexical.py"] += b"\n# Different reference helper bytes\n"
        message = "Shared helper changed: src/rag/lexical.py"
    else:
        before = candidate["src/report_template.py"]
        old, new = {
            "extractor_body": (b"return text.strip()", b"return text.rstrip()"),
            "missing_callee": (b"def _remove_section(text, heading):", b"def unrelated_section(text, heading):"),
            "governance_value": (
                b"This report is a preparedness planning draft.",
                b"Changed synthetic governance notice.",
            ),
        }[mutation]
        candidate["src/report_template.py"] = before.replace(old, new, 1)
        assert candidate["src/report_template.py"] != before
        message = "Stable template dependency"
    with pytest.raises(AssertionError, match=message):
        verify_real_shared_helpers(candidate)


@pytest.mark.parametrize(
    "mutation",
    ["prompt", "analysis", "raw", "assembly", "rubric", "order", "budget", "boolean", "stop_on_failure", "code_hash"],
)
def test_validate_rejects_tampering_even_with_recomputed_internal_and_external_hashes(
    monkeypatch, tmp_path, bundle, mutation
):
    from src.model_evidence import json_sha256, text_sha256

    rebuilt = copy.deepcopy(bundle)
    case = bundle["cases"][0]
    if mutation == "prompt":
        case["arms"]["baseline"]["prompt"] += " Added instruction."
        case["arms"]["baseline"]["prompt_sha256"] = text_sha256(case["arms"]["baseline"]["prompt"])
    elif mutation == "analysis":
        case["arms"]["candidate"]["analysis"]["community"] = {"population": 999}
        case["arms"]["candidate"]["analysis_sha256"] = json_sha256(case["arms"]["candidate"]["analysis"])
    elif mutation == "raw":
        case["raw_inputs"]["form"]["extra_context"] = "Changed raw request"
        case["raw_inputs_sha256"] = json_sha256(case["raw_inputs"])
    elif mutation == "assembly":
        case["shared_rag"]["context"] += " Altered evidence."
        case["shared_rag_sha256"] = json_sha256(case["shared_rag"])
    elif mutation == "rubric":
        case["review"]["items"][0]["question"] = "Assume every claim is correct?"
    elif mutation == "order":
        bundle["execution_plan"]["request_order"].reverse()
    elif mutation == "budget":
        bundle["execution_plan"]["max_requests"] = 7
    elif mutation == "boolean":
        bundle["execution_plan"]["parameters"]["sdk_retries"] = False
    elif mutation == "stop_on_failure":
        bundle["execution_plan"]["stop_on_first_request_failure"] = False
    else:
        bundle["source_identity"]["experiment_file_sha256"][comparison.TEST_PATH] = "0" * 64
    _, digest = _write_test_bundle(tmp_path, bundle)
    monkeypatch.setattr(comparison, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(comparison, "prepare_bundle", lambda: rebuilt)
    with pytest.raises(comparison.ComparisonBlocked, match="prepared_content_or_source_drift"):
        comparison.validate_prepared(digest)


def test_changed_case_or_experiment_code_changes_rebuilt_binding(monkeypatch, fixed_sources):
    baseline = comparison.prepare_bundle()
    original = comparison._working_bytes
    monkeypatch.setattr(
        comparison, "_working_bytes", lambda name: original(name) + (b"\n" if name == comparison.TEST_PATH else b"")
    )
    assert baseline["source_identity"] != comparison.prepare_bundle()["source_identity"]
    raw_cases = comparison._synthetic_cases()
    raw_cases[0]["raw_inputs"]["form"]["extra_context"] += " Added synthetic detail."
    monkeypatch.setattr(comparison, "_synthetic_cases", lambda: raw_cases)
    assert baseline["cases"][0]["raw_inputs_sha256"] != comparison.prepare_bundle()["cases"][0]["raw_inputs_sha256"]


def test_cli_writes_utf8_exclusively_and_validate_is_read_only(monkeypatch, tmp_path, bundle):
    monkeypatch.setattr(comparison, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(comparison, "prepare_bundle", lambda: copy.deepcopy(bundle))
    old_campaign = tmp_path / "output" / "unrelated-historical-campaign"
    old_campaign.mkdir(parents=True)
    old_file = old_campaign / "untouched.txt"
    old_file.write_text("Prior campaign stays intact.", encoding="utf-8")
    assert comparison.main(["prepare"]) == 0
    path = tmp_path / "output" / comparison.CAMPAIGN / "prepared.json"
    content = path.read_bytes()
    assert json.loads(content.decode("utf-8")) == bundle
    digest = hashlib.sha256(content).hexdigest()
    assert comparison.main(["validate", "--expected-prepared-file-sha256", digest]) == 0
    assert path.read_bytes() == content
    with pytest.raises(SystemExit) as rejected:
        comparison.main(["prepare"])
    assert rejected.value.code == 2
    with pytest.raises(comparison.ComparisonBlocked, match="prepared_file_sha256_mismatch"):
        comparison.validate_prepared("0" * 64)
    assert path.read_bytes() == content
    assert old_file.read_text(encoding="utf-8") == "Prior campaign stays intact."
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("args", [["run"], ["prepare", "--output", "elsewhere"], ["validate"]])
def test_cli_has_no_run_custom_output_or_unbound_validation(args):
    with pytest.raises(SystemExit) as rejected:
        comparison.main(args)
    assert rejected.value.code == 2


def test_prepare_failure_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(comparison, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        comparison, "prepare_bundle", lambda: (_ for _ in ()).throw(comparison.ComparisonBlocked("drift"))
    )
    with pytest.raises(SystemExit):
        comparison.main(["prepare"])
    assert not (tmp_path / "output").exists()
