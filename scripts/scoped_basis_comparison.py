"""Prepare/validate one offline synthetic comparison; there is no execution mode.

Both complete initial prompts are rebuilt from fixed Git sources. No model,
retrieval, dotenv, quota, historical campaign, or production pipeline is used.
"""

from __future__ import annotations

import argparse
import builtins
import copy
import hashlib
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CAMPAIGN = "scoped-basis-comparison-v1"
BASELINE = "933d26b8d71242e2198c48a5770ab77299892a7c"
CANDIDATE = "f69e62f0a9744eb04afd52abbf7e2b8dee16774f"
SCRIPT_PATH = "scripts/scoped_basis_comparison.py"
TEST_PATH = "tests/test_scoped_basis_comparison.py"
ARM_FILES = ("src/agents/report_agent.py", "src/report_template.py")
ALLOWED_SOURCE_CHANGES = frozenset(
    (*ARM_FILES, "src/report_basis.py", "src/report_generation_quality.py", "src/report_workflow.py")
)
REVIEW_STATES = ("supported", "partial_or_scope_changed", "insufficient", "not_generated_or_unassessable")


class ComparisonBlocked(ValueError):
    """A fixed-source or frozen-artifact precondition failed before any write."""


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _git(*args, input_data=None):
    result = subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=PROJECT_ROOT, input=input_data, capture_output=True, check=False, timeout=30
    )
    if result.returncode:
        raise ComparisonBlocked("fixed_git_source_unavailable")
    return result.stdout


def _git_sources(commit):
    if _git("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip() != commit:
        raise ComparisonBlocked("fixed_git_commit_mismatch")
    # Raw blobs avoid git archive's checkout/EOL transformations on Windows.
    entries = []
    for entry in _git("ls-tree", "-r", "-z", commit, "--", "src").split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if path.startswith(b"src/") and path.endswith(b".py"):
            if mode not in {b"100644", b"100755"} or kind != b"blob":
                raise ComparisonBlocked("unsupported_git_source_entry")
            entries.append((oid, path.decode("utf-8")))
    batch = _git("cat-file", "--batch", input_data=b"".join(oid + b"\n" for oid, _ in entries))
    sources, cursor = {}, 0
    for oid, path in entries:
        boundary = batch.index(b"\n", cursor)
        actual_oid, kind, size = batch[cursor:boundary].split()
        start, end = boundary + 1, boundary + 1 + int(size)
        if actual_oid != oid or kind != b"blob" or batch[end : end + 1] != b"\n":
            raise ComparisonBlocked("invalid_git_blob_batch")
        sources[path] = batch[start:end]
        cursor = end + 1
    if cursor != len(batch):
        raise ComparisonBlocked("unexpected_git_blob_batch_data")
    return sources


def _working_bytes(relative):
    path = PROJECT_ROOT / relative
    if path.is_symlink() or not path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise ComparisonBlocked("source_path_outside_project")
    return path.read_bytes()


def _source_snapshot():
    baseline, candidate = _git_sources(BASELINE), _git_sources(CANDIDATE)
    changed = {path for path in baseline.keys() | candidate.keys() if baseline.get(path) != candidate.get(path)}
    if changed != ALLOWED_SOURCE_CHANGES or "src/report_basis.py" in baseline:
        raise ComparisonBlocked("unexpected_git_source_change")
    current_paths = {path.relative_to(PROJECT_ROOT).as_posix() for path in (PROJECT_ROOT / "src").rglob("*.py")}
    if current_paths != candidate.keys():
        raise ComparisonBlocked("current_source_inventory_drift")
    working_hashes = {}
    for path, expected in candidate.items():
        actual = _working_bytes(path)
        # Git and checkout line endings may differ. Bind
        # the actual file bytes as well, so an existing bundle still detects drift.
        if actual.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n") != expected.decode("utf-8").replace(
            "\r\n", "\n"
        ).replace("\r", "\n"):
            raise ComparisonBlocked(f"current_source_drift:{path}")
        working_hashes[path] = _sha(actual)
    identity = {
        "baseline_commit": BASELINE,
        "candidate_commit": CANDIDATE,
        "changed_source_paths": sorted(changed),
        "initial_builder_paths": {"baseline": list(ARM_FILES), "candidate": [*ARM_FILES, "src/report_basis.py"]},
        "git_python_source_sha256": {
            "baseline": {path: _sha(value) for path, value in sorted(baseline.items())},
            "candidate": {path: _sha(value) for path, value in sorted(candidate.items())},
        },
        "current_python_source_sha256": dict(sorted(working_hashes.items())),
        "experiment_file_sha256": {path: _sha(_working_bytes(path)) for path in (SCRIPT_PATH, TEST_PATH)},
        "shared_helper_check": "All tracked src Python sources outside the five listed changes are identical.",
        "checkout_comparison": "UTF-8 with universal-newline comparison; actual checkout bytes also hashed.",
    }
    return identity, baseline, candidate


def _arm_builders(sources, arm):
    """Execute only the two complete trusted builders and the candidate basis.

    The sole local import substitution binds the candidate template to its fixed
    basis module. Shared dependencies use the identical, verified checkout. No
    sys.modules entry or production module is patched.
    """
    basis = None
    if arm == "candidate":
        basis = ModuleType("fixed_candidate_report_basis")
        # Fixed trusted Git source, verified before either arm is built.
        exec(  # nosec B102
            compile(sources["src/report_basis.py"], f"git:{CANDIDATE}:src/report_basis.py", "exec"), vars(basis)
        )

    def fixed_basis_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "src.report_basis" and basis is not None and level == 0:
            return basis
        return builtins.__import__(name, globals, locals, fromlist, level)

    namespaces = []
    for path in ARM_FILES:
        namespace = {"__name__": f"fixed_{arm}_{Path(path).stem}", "__builtins__": dict(vars(builtins))}
        namespace["__builtins__"]["__import__"] = fixed_basis_import
        # Complete fixed trusted builder; no user-provided code is evaluated.
        exec(  # nosec B102
            compile(sources[path], f"git:{BASELINE if arm == 'baseline' else CANDIDATE}:{path}", "exec"), namespace
        )
        namespaces.append(namespace)
    return namespaces[0]["ReportAgent"], namespaces[1]["build_report_prompt"]


def _synthetic_cases():
    """New development material, deliberately not official excerpts or a gold set."""
    from src.agents.planner_agent import PlannerAgent

    specs = (
        (
            "household-conditions-campus-records",
            (
                "Synthetic development household note: Among households that have recorded a member's support "
                "needs, a written evacuation planning record lists the nominated support contact and the assistance "
                "the householder says they may need when leaving. The record describes self-reported household "
                "needs and contact details, not observed service delivery.",
                "Synthetic development campus memo: The fictional Cedar Lantern campus memo lists a register of "
                "document owners and review dates. The memo is an administrative record.",
            ),
            {},
            "A fictional campus has supplied an administrative document register.",
            ("evacuation", "communications"),
            "Identify records of evacuation support needs and communication contacts for local review.",
        ),
        (
            "period-denominators-approximate-area",
            (
                "Synthetic development catalogue: A fictional archive lists 18 preparedness contact forms. This number counts "
                "forms, not residents or households. The catalogue contains no demographic measurements.",
            ),
            {
                "matched_location": "Fable Reach synthetic statistical area",
                "indicators": {
                    "population": 1800,
                    "older_people_pct": 18,
                    "no_car_households_pct": 18,
                    "language_other_than_english_pct": None,
                    "language_support_needed": "high",
                    "matched_sa2_count": 2,
                    "geography_type": "Synthetic approximate aggregate of two SA2-like rows, not a campus population",
                },
                "data_quality": {
                    "source_period": "2021 fictional household/resident tables; 2023 synthetic population estimate",
                    "latest_source_year": 2023,
                    "source_age_years": None,
                    "assessed_for_year": None,
                    "freshness": "Synthetic historical planning baseline; no current observation",
                    "match_quality": "approximate synthetic aggregate",
                    "match_method": "fictional_two_row_aggregation",
                    "match_basis": "Older people: percent of residents. No-car: percent of households. Campus headcount unknown.",
                },
                "vulnerability_notes": [
                    "The high language-support label is a synthetic rule priority, not a measured language percentage."
                ],
                "data_source_note": "All profile values are fabricated; no ABS data or real community was read.",
            },
            "A fictional campus is situated in the invented Fable Reach comparison area.",
            ("communications", "vulnerable_people"),
            "Review communication records and the definitions used in the supplied population profile.",
        ),
        (
            "conflicting-summary-narrow-maintenance-record",
            (
                "Synthetic development property note: Routine property maintenance increases building defects and "
                "reduces the chance of retaining intact fixtures. A later line describes the same maintenance as "
                "reducing building defects.",
                "Synthetic development maintenance log: A fictional inspection entry records an external wall-panel "
                "gap and a maintenance request. Completion status is unrecorded.",
            ),
            {},
            "No staff credential record or exercise calendar is supplied for this fictional campus.",
            ("first_aid", "human_review"),
            "Identify local staff qualification and exercise records for responsible review.",
        ),
    )
    result = []
    for case_id, passages, community, extra, focus_ids, priority in specs:
        focuses = [PlannerAgent.canonical_focus_concept(identity) for identity in focus_ids]
        chunks = [
            {
                "source_id": f"synthetic-scoped-basis-{case_id}-{index}",
                "chunk_id": f"synthetic-chunk-{index}",
                "title": f"Synthetic development text {index}",
                "agency": "Fictional development fixture, not an official agency",
                "text": passage,
                "chunk_sha256": _sha(passage.encode("utf-8")),
                "synthetic_development": True,
            }
            for index, passage in enumerate(passages, 1)
        ]
        result.append(
            {
                "case_id": case_id,
                "raw_inputs": {
                    "profile": {
                        "state": "Queensland",
                        "setting_type": "campus",
                        "scenario_concept": {"id": "school_preparedness", "label": "School bushfire preparedness"},
                    },
                    "data": {"sources": [], "data_limitations": ["Synthetic development material only."]},
                    "community": community,
                    "risk_context": {
                        "risk_points": ["Synthetic R3 cue: consider gaps in planning records."],
                        "assumptions": [],
                    },
                    "plan": {
                        "planning_priorities": [priority],
                        "focus_area_concepts": focuses,
                    },
                    "knowledge": {"status_label": "Synthetic development passages", "retrieved_chunks": chunks},
                    "area_selection": None,
                    "form": {
                        "location": "Cedar Lantern fictional campus, Queensland",
                        "audience": "Fictional campus administrative reviewers",
                        "scenario": "School bushfire preparedness",
                        "concerns": [focus["label"] for focus in focuses],
                        "timeframe": "Future planning review; no operational schedule supplied",
                        "extra_context": extra,
                        "governance_context": "Synthetic development exercise: all places, passages and numbers are invented.",
                    },
                },
            }
        )
    return result


def _review_rubric(case_id):
    questions = [
        (
            "citation_presence",
            "Are external claims accompanied by recognisable supplied citation tokens with valid source bindings?",
        ),
        ("lexical_fidelity", "Do cited descriptions retain the actual visible words' meaning and qualifications?"),
        ("source_support", "Does the evidence actually submitted support each sourced description on its own terms?"),
        ("applicability", "Is source support distinguished from applicability to the fictional local setting?"),
        (
            "retained_content",
            "Does the draft retain useful narrow sourced content, planning tasks and explicit limits, rather than succeeding by silence?",
        ),
    ]
    specific = {
        "household-conditions-campus-records": [
            (
                "household_scope",
                "Are the household audience, recorded-support-needs condition and contact/assistance record object preserved?",
            ),
            ("local_application", "Are campus adaptations separate unverified proposals with confirmation needs?"),
            (
                "campus_content",
                "Is the independently supported campus recordkeeping content retained without a safety inference?",
            ),
        ],
        "period-denominators-approximate-area": [
            (
                "period_area",
                "Are the supplied historical periods and approximate two-row aggregation retained without a campus headcount inference?",
            ),
            (
                "denominators_unknown",
                "Are the two 18-percent values tied to their different denominators and the missing language measurement left unknown?",
            ),
            (
                "provenance_separation",
                "Are rule priorities distinguished from P2 measurements, without using the 18-form passage to support demographic numbers?",
            ),
        ],
        "conflicting-summary-narrow-maintenance-record": [
            (
                "contradiction",
                "Is conflicting source wording flagged rather than silently corrected or converted into effect advice?",
            ),
            (
                "missing_local_records",
                "Do local qualifications and frequency remain unverified without invented credentials or schedules?",
            ),
            (
                "narrow_record",
                "Is the supported wall-panel inspection/request record retained without claiming completed repairs or omitting all source content?",
            ),
        ],
    }
    return {
        "status": "not_observed",
        "allowed_states": list(REVIEW_STATES),
        "state_scope": "Each state judges one dimension, not overall claim correctness or accuracy. Citation presence does not establish source support or applicability.",
        "span_requirement": "Every future judgment requires a reason and relevant output/submitted-evidence spans. For not_generated_or_unassessable, output_span may be null when no assessable output exists; explain why. Planned visibility is not SDK submission.",
        "items": [
            {
                "id": f"rubric_{key}",
                "question": question,
                "by_arm": {
                    arm: {"state": None, "output_span": None, "submitted_evidence_span": None, "reason": None}
                    for arm in ("baseline", "candidate")
                },
            }
            for key, question in (*questions, *specific[case_id])
        ],
    }


def _build_arm(raw, assembly, builders):
    from src.evidence_confidence import build_evidence_confidence_rows
    from src.model_evidence import json_sha256, text_sha256, validate_recorded_assembly
    from src.source_attribution import canonical_source_token_data

    copied = copy.deepcopy(raw)
    report_agent, build_prompt = builders
    analysis = {
        key: copied[key]
        for key in ("profile", "data", "community", "risk_context", "plan", "knowledge", "area_selection")
    }
    analysis["rag_context_assembly"] = copy.deepcopy(assembly)
    analysis["prompt_context"] = report_agent().run(
        analysis["profile"],
        analysis["data"],
        analysis["risk_context"],
        analysis["plan"],
        community_result=analysis["community"],
        knowledge_result=analysis["knowledge"],
        area_selection=analysis["area_selection"],
        rag_assembly=analysis["rag_context_assembly"],
    )
    analysis["evidence_confidence"] = build_evidence_confidence_rows(analysis)
    prompt = build_prompt(**copied["form"], analysis=analysis, area_selection=analysis["area_selection"])
    if validate_recorded_assembly(assembly, analysis) != assembly["visible_chunks"]:
        raise ComparisonBlocked("invalid_planned_assembly")
    if prompt.count(assembly["context"]) != 1 or analysis["rag_context_assembly"] != assembly:
        raise ComparisonBlocked("rag_assembly_changed_or_duplicated")
    tokens = canonical_source_token_data(
        official_sources=analysis["data"]["sources"], rag_sources=analysis["knowledge"]["retrieved_chunks"]
    )
    return {
        "request_kind": "initial",
        "visibility_status": "planned_not_submitted",
        "raw_inputs_sha256": json_sha256(raw),
        "shared_rag_sha256": json_sha256(assembly),
        "source_tokens": tokens,
        "analysis": analysis,
        "analysis_sha256": json_sha256(analysis),
        "prompt_context_sha256": text_sha256(analysis["prompt_context"]),
        "prompt": prompt,
        "prompt_sha256": text_sha256(prompt),
    }


def prepare_bundle():
    """Return a deterministic bundle after source verification; write nothing."""
    identity, baseline, candidate = _source_snapshot()
    from src.model_evidence import json_sha256
    from src.rag.context import assemble_planning_context
    from src.source_attribution import format_rag_citation_token

    builders = {"baseline": _arm_builders(baseline, "baseline"), "candidate": _arm_builders(candidate, "candidate")}
    cases = []
    for case in _synthetic_cases():
        raw = case["raw_inputs"]
        before = copy.deepcopy(raw)
        assembly = assemble_planning_context(raw["knowledge"], focus_concepts=raw["plan"]["focus_area_concepts"])
        arms = {arm: _build_arm(raw, assembly, builder) for arm, builder in builders.items()}
        if raw != before or arms["baseline"]["source_tokens"] != arms["candidate"]["source_tokens"]:
            raise ComparisonBlocked("raw_input_or_citation_drift")
        for arm in arms.values():
            for chunk in raw["knowledge"]["retrieved_chunks"]:
                if arm["prompt"].count(chunk["text"]) != 1 or format_rag_citation_token(chunk) not in arm["prompt"]:
                    raise ComparisonBlocked("synthetic_passage_missing_or_changed")
        cases.append(
            {
                **case,
                "raw_inputs_sha256": json_sha256(raw),
                "shared_rag": assembly,
                "shared_rag_sha256": json_sha256(assembly),
                "arms": arms,
                "review": _review_rubric(case["case_id"]),
            }
        )
    order = [
        {"case_id": case["case_id"], "arm": arm}
        for index, case in enumerate(cases)
        for arm in (("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline"))
    ]
    return {
        "schema": CAMPAIGN,
        "campaign": CAMPAIGN,
        "source_identity": identity,
        "material_status": "synthetic_development",
        "limitations": [
            "New synthetic material driven by previously observed development failures; not official excerpts, a holdout, or an independent gold standard.",
            "Combined initial-generation change: source stratification, frozen P2 basis, body rules and effect wording. Not a single-factor experiment; revision and repair are untested.",
            "Synthetic text uses existing production RAG framing; it cannot establish a root cause involving production official-source labels.",
            "Readable fixture code and rubric are not independent truth labels. Citation presence, lexical fidelity and applicability require separate human judgments; abstention alone is not superiority.",
            "Only prompt preparation is observed. Planned evidence visibility is not SDK submission, provider receipt, model attention or semantic accuracy.",
            "Any future model calls require a separately authorised execution boundary; this tool has no run mode or call journal.",
        ],
        "execution_plan": {
            "status": "planned",
            "max_requests": 6,
            "request_order": order,
            "request_kind": "initial",
            "attempts_per_case_arm": 1,
            "stop_on_first_request_failure": True,
            "failure_types": ["length", "protocol", "timeout", "transport"],
            "replacement_requests": False,
            "parameters": {"temperature": 0.2, "max_output_tokens": 2300, "thinking": "disabled", "sdk_retries": 0},
            "max_total_output_tokens": 13800,
            "structural_repair": False,
            "revision": False,
            "model_judge": False,
        },
        "observations": {
            "status": "not_observed",
            "model_calls": 0,
            "model_alias": None,
            "provider_response": None,
            "usage": None,
            "elapsed_seconds": None,
            "cost": None,
            "semantic_accuracy": None,
        },
        "production_enabled": False,
        "release_gate": "inactive",
        "cases": cases,
    }


def _prepared_path():
    path = PROJECT_ROOT / "output" / CAMPAIGN / "prepared.json"
    if any(part.is_symlink() for part in (path, path.parent, path.parent.parent)):
        raise ComparisonBlocked("prepared_path_symlink")
    if not path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise ComparisonBlocked("prepared_path_outside_project")
    return path


def validate_prepared(expected_prepared_file_sha256):
    """Verify an external file hash, then rebuild and compare every frozen field."""
    path = _prepared_path()
    content = path.read_bytes()
    if _sha(content) != expected_prepared_file_sha256:
        raise ComparisonBlocked("prepared_file_sha256_mismatch")
    prepared = json.loads(content.decode("utf-8"))
    # JSON comparison, unlike Python equality, distinguishes 0/False and 6/6.0.
    if json.dumps(prepared, sort_keys=True) != json.dumps(prepare_bundle(), sort_keys=True):
        raise ComparisonBlocked("prepared_content_or_source_drift")
    return prepared


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="Write the fixed prepared.json once; no model calls.")
    validator = subparsers.add_parser("validate", help="Read and rebuild the fixed prepared.json; no writes.")
    validator.add_argument("--expected-prepared-file-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            bundle = prepare_bundle()
            path = _prepared_path()
            payload = (json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(payload)
            print(json.dumps({"campaign": CAMPAIGN, "prepared_file_sha256": _sha(payload), "model_calls": 0}))
        else:
            validate_prepared(args.expected_prepared_file_sha256)
            print(json.dumps({"campaign": CAMPAIGN, "validated": True, "model_calls": 0}))
    except (ComparisonBlocked, OSError, ValueError, UnicodeError) as error:
        parser.exit(2, f"Blocked: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
