"""Offline, fixed-source preparation of the citation/criteria development comparison.

No retrieval, configuration, credentials, model, or historical artifact is read.
The separate guarded runner is the only execution entry point.
"""

from __future__ import annotations

import argparse
import builtins
import copy
import hashlib
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CAMPAIGN = "citation-criteria-comparison-v1"
BASELINE = "3199c7d938a719e08d5b6550aad8b04759107039"
CANDIDATE = "b74cdd8af3c932c8cbf7322d6226a6579bfcf2cd"
EXPERIMENT_FILES = (
    "scripts/citation_criteria_comparison.py",
    "scripts/run_citation_criteria_comparison.py",
    "tests/test_citation_criteria_comparison.py",
    "tests/test_run_citation_criteria_comparison.py",
)
HELPER_FILES = (
    "scripts/scoped_basis_comparison.py",
    "scripts/run_scoped_basis_comparison.py",
    "scripts/evaluate_body_evidence_deepseek.py",
    "scripts/evaluate_body_evidence_ab.py",
    "scripts/evaluation_artifacts.py",
)
PARAMETERS = {
    "temperature": 0.2,
    "max_output_tokens": 2300,
    "thinking": "disabled",
    "top_p": 0.8,
    "timeout_seconds": 180,
    "sdk_retries": 0,
    "stream": False,
    "seed_sent": False,
    "tools_sent": False,
}


class ComparisonBlocked(ValueError):
    """A fixed source or artifact precondition failed before any write."""


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _git(*args, input_data=None):
    result = subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=PROJECT_ROOT, input=input_data, capture_output=True, check=False, timeout=30
    )
    if result.returncode:
        raise ComparisonBlocked("fixed_git_source_unavailable")
    return result.stdout


def _git_sources(commit):
    if commit not in (BASELINE, CANDIDATE):
        raise ComparisonBlocked("fixed_git_commit_required")
    if _git("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip() != commit:
        raise ComparisonBlocked("fixed_git_commit_mismatch")
    entries = []
    for entry in _git("ls-tree", "-r", "-z", commit, "--", "src").split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if path.endswith(b".py"):
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
        sources[path], cursor = batch[start:end], end + 1
    if cursor != len(batch):
        raise ComparisonBlocked("unexpected_git_blob_batch_data")
    return sources


def _working_bytes(relative):
    path = PROJECT_ROOT / relative
    if path.is_symlink() or not path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise ComparisonBlocked("source_path_outside_project")
    return path.read_bytes()


def _normal(content):
    return content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _source_snapshot():
    baseline, candidate = _git_sources(BASELINE), _git_sources(CANDIDATE)
    changed = {path for path in baseline.keys() | candidate.keys() if baseline.get(path) != candidate.get(path)}
    if changed != {"src/report_template.py"}:
        raise ComparisonBlocked("unexpected_git_source_change")
    inventory = {path.relative_to(PROJECT_ROOT).as_posix() for path in (PROJECT_ROOT / "src").rglob("*.py")}
    if inventory != candidate.keys():
        raise ComparisonBlocked("current_source_inventory_drift")
    actual = {}
    for path, expected in candidate.items():
        content = _working_bytes(path)
        if _normal(content) != _normal(expected):
            raise ComparisonBlocked(f"current_source_drift:{path}")
        actual[path] = _sha(content)
    helper_git = {}
    for path in HELPER_FILES:
        expected = _git("show", f"{CANDIDATE}:{path}")
        if _normal(_working_bytes(path)) != _normal(expected):
            raise ComparisonBlocked(f"shared_helper_drift:{path}")
        helper_git[path] = _sha(expected)
    return (
        {
            "baseline_commit": BASELINE,
            "candidate_commit": CANDIDATE,
            "changed_source_paths": sorted(changed),
            "git_python_source_sha256": {
                arm: {path: _sha(value) for path, value in sorted(sources.items())}
                for arm, sources in (("baseline", baseline), ("candidate", candidate))
            },
            "current_python_source_sha256": dict(sorted(actual.items())),
            "shared_helper_git_sha256": helper_git,
            "experiment_and_helper_sha256": {
                path: _sha(_working_bytes(path)) for path in (*EXPERIMENT_FILES, *HELPER_FILES)
            },
            "checkout_comparison": "Universal-newline Git comparison; actual checkout bytes independently bound.",
        },
        baseline,
        candidate,
    )


def _arm_builders(sources, commit):
    # Complete trusted fixed Git builders; both use the same verified shared basis/helpers.
    namespaces = []
    for path in ("src/agents/report_agent.py", "src/report_template.py"):
        namespace = {"__name__": f"fixed_{commit}_{Path(path).stem}", "__builtins__": dict(vars(builtins))}
        code = compile(sources[path], f"git:{commit}:{path}", "exec")
        exec(code, namespace)  # nosec B102
        namespaces.append(namespace)
    return namespaces[0]["ReportAgent"], namespaces[1]["build_report_prompt"]


def _synthetic_cases():
    from src.agents.planner_agent import PlannerAgent

    specs = (
        (
            "worksheet-catalogue-contact-review",
            "Juniper Quay",
            ("communications", "roles"),
            "The campus administrative team is preparing a review of its paperwork inventory and responsibility for the warning-contact list.",
            "Review who maintains the campus warning-contact list and how changes to that list are recorded.",
            "synthetic-jq-catalogue",
            "jq-catalogue-1",
            "Fictional Marrow Collection catalogue, drawer K",
            "The fictional Marrow Collection catalogue lists 27 blank communication-contact worksheet templates in drawer K. The catalogue entry describes archived templates deposited by education offices between 2016 and 2019.",
        ),
        (
            "candidate-file-intake",
            "Thistle Reach",
            ("candidate_assembly_points", "human_review"),
            "The campus administrative team is preparing its next review of candidate assembly-point paperwork.",
            "Ask the campus records lead to obtain the documents needed for the next candidate-location review and record responsibility for that review.",
            "synthetic-tr-intake",
            "tr-intake-1",
            "Fictional Thistle Reach candidate-location file intake ledger",
            "The fictional Thistle Reach candidate-location file intake ledger records file L-31 as received on 6 February 2025, file L-44 on 9 February 2025, and file L-58 on 14 February 2025. Each receipt row contains an envelope reference and the receiving clerk's initials.",
        ),
        (
            "conditional-documentary-audit",
            "Rookmere",
            ("candidate_assembly_points", "roles"),
            "The campus administrative team is preparing a desk review of candidate-location files. The campus has not supplied the individual files for this exercise.",
            "Have the campus records lead review the candidate-location files and record which documentary requirements need confirmation.",
            "synthetic-rm-audit",
            "rm-audit-1",
            "Fictional campus candidate-file desk-audit procedure D-7",
            "Under fictional campus candidate-file desk-audit procedure D-7, a candidate-location file may enter documentary audit only if it carries a file identifier, a named custodian and a signed revision sheet, unless it is marked withdrawn. A withdrawn file is not eligible for documentary audit. Exception: for a legacy file, a dated accession sheet may replace the signed revision sheet when the records supervisor has countersigned the accession sheet. The exception does not apply to withdrawn files. Admission concerns completeness of the file for desk audit.",
        ),
    )
    cases = []
    for case_id, place, focuses, extra, task, source_id, chunk_id, title, passage in specs:
        concepts = [PlannerAgent.canonical_focus_concept(focus) for focus in focuses]
        cases.append(
            {
                "case_id": case_id,
                "raw_inputs": {
                    "profile": {
                        "state": "Queensland",
                        "setting_type": "campus",
                        "scenario_concept": {"id": "school_preparedness", "label": "School bushfire preparedness"},
                    },
                    "data": {"sources": [], "data_limitations": ["Synthetic development material only."]},
                    "community": {},
                    "risk_context": {"risk_points": [], "assumptions": []},
                    "plan": {"planning_priorities": [task], "focus_area_concepts": concepts},
                    "knowledge": {
                        "status_label": "Synthetic development passages",
                        "retrieved_chunks": [
                            {
                                "source_id": source_id,
                                "chunk_id": chunk_id,
                                "title": title,
                                "agency": "Fictional development fixture, not an official agency",
                                "text": passage,
                                "chunk_sha256": _sha(passage.encode("utf-8")),
                                "synthetic_development": True,
                            }
                        ],
                    },
                    "area_selection": None,
                    "form": {
                        "location": f"{place} fictional campus, Queensland",
                        "audience": "Campus administrative planning team",
                        "scenario": "School bushfire preparedness",
                        "concerns": [item["label"] for item in concepts],
                        "timeframe": "Next planning review; date to be agreed.",
                        "extra_context": extra,
                        "governance_context": "Synthetic development exercise. All named campuses, collections, passages and records are invented.",
                    },
                },
            }
        )
    return cases


def _review_rubric(index):
    questions = (
        (
            "Retain a useful narrow archived-template fact with citation; absence is not_generated_or_unassessable, not improvement.",
            "Keep 27 tied to archived blank templates, not current contacts, people or households; absent number is not_generated_or_unassessable.",
            "Does a citation support the entire sentence/bullet/cell rather than a local warning-contact task? An absent relationship is not_generated_or_unassessable, not clean support.",
            "Keep the local task separate as an unverified proposal with a responsible role and concrete confirmation; missing task is insufficient.",
            "Do campus ownership, update and effect assertions stay within evidence? Explicit unknowns can be supported; silence is not_generated_or_unassessable.",
            "Does source use serve the section without becoming an official warning service or current register? No use is not_generated_or_unassessable.",
        ),
        (
            "Retain the narrow receipt ledger without completed assessment, approval or availability; absent record content is not_generated_or_unassessable.",
            "Does section 9 state the criteria gap and who must obtain/confirm criteria? Missing required gap response is insufficient.",
            "Avoid inventing established selection requirements from receipt dates, initials or general knowledge; an explicit gap can be supported, an empty section cannot.",
            "Qualify the requested obtain/review task with owner and confirmation, not a source-backed standard; missing or misattributed task is insufficient.",
            "Limit file/venue assertions to record status, not physical safety, suitability, operation or approval; pure omission is not_generated_or_unassessable.",
            "Attach citations only to ledger-supported claims, with no section quota; explicit gaps need no citation but do not prove positive citation binding.",
        ),
        (
            "Retain useful cited documentary criteria, not blanket no-criteria abstention; silence or abstention is insufficient.",
            "Preserve the necessary identifier, named custodian and signed revision sheet without converting only-if into sufficiency; whole-rule omission is insufficient.",
            "Preserve the withdrawn-file exclusion including legacy files; dropping it changes scope and whole-rule omission is insufficient.",
            "Preserve the legacy exception: dated accession sheet, supervisor countersignature, replacing only the signed revision sheet; omission is insufficient.",
            "Distinguish documentary audit completeness from physical assembly, venue suitability, status or approval; no substance is not_generated_or_unassessable.",
            "Do not claim local files meet the rules; keep the task, owner and concrete confirmation needs. A missing task is insufficient.",
            "Attach citations to sourced rules and separate local tasks; no cited rule is insufficient for this positive control.",
        ),
    )[index]
    return {
        "status": "not_observed",
        "states": {
            "supported": "Actual SDK evidence supports this dimension, including an explicitly required gap.",
            "partial_or_scope_changed": "A material qualifier, object or audience changes.",
            "insufficient": "Unsupported assertion or a required substantive response missing from an assessable report.",
            "not_generated_or_unassessable": "No assessable output/evidence, or an optional relationship is absent.",
        },
        "span_protocol": "Each judgment needs a reason, exact Unicode half-open raw/cleaned output spans and actual SDK evidence spans with matching text. For absence, cite the related whole section and searched concept, never fabricate a span. Planned visibility is not submission.",
        "interpretation": "Dimension judgments, not claim accuracy or aggregate scores. Citation presence is separate from support and applicability. Do not penalise an administrative R3 task for lacking a bibliographic citation.",
        "items": [
            {
                "id": f"dimension_{index + 1}_{number}",
                "question": question,
                "by_arm": {
                    arm: {
                        "state": None,
                        "reason": None,
                        "raw_output_span": None,
                        "cleaned_output_span": None,
                        "submitted_evidence_span": None,
                        "absence_section_span": None,
                        "searched_concept": None,
                    }
                    for arm in ("baseline", "candidate")
                },
            }
            for number, question in enumerate(questions, 1)
        ],
    }


def prepare_bundle():
    identity, baseline, candidate = _source_snapshot()
    from scripts.scoped_basis_comparison import _build_arm
    from src.model_evidence import json_sha256
    from src.rag.context import assemble_planning_context
    from src.source_attribution import format_rag_citation_token

    builders = {
        arm: _arm_builders(sources, commit)
        for arm, sources, commit in (("baseline", baseline, BASELINE), ("candidate", candidate, CANDIDATE))
    }
    cases = []
    for index, case in enumerate(_synthetic_cases()):
        raw = case["raw_inputs"]
        before = copy.deepcopy(raw)
        assembly = assemble_planning_context(raw["knowledge"], focus_concepts=raw["plan"]["focus_area_concepts"])
        arms = {arm: _build_arm(raw, assembly, builder) for arm, builder in builders.items()}
        if raw != before or arms["baseline"]["analysis"] != arms["candidate"]["analysis"]:
            raise ComparisonBlocked("raw_input_or_analysis_drift")
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
                "review": _review_rubric(index),
            }
        )
    return {
        "schema": CAMPAIGN,
        "campaign": CAMPAIGN,
        "source_identity": identity,
        "material_status": "synthetic_development",
        "limitations": [
            "Fresh synthetic development cases; not official excerpts, holdout or independently labelled benchmark.",
            "Only shared initial prompt guidance differs. No claim of immutable model weights, general improvement, or production root cause; revision and repair untested.",
            "Existing synthetic O1/P2 framing remains a confound. Tokens do not attest official indexing or authority.",
            "Rubric is review design, not answers or a gold standard. No aggregate accuracy or scores; silence is not superiority.",
            "Prepared visibility is not SDK submission, provider receipt, attention or semantic support. Execution requires explicit separate flags.",
        ],
        "execution_plan": {
            "status": "planned",
            "max_requests": 6,
            "request_kind": "initial",
            "attempts_per_case_arm": 1,
            "request_order": [
                {"case_id": case["case_id"], "arm": arm}
                for index, case in enumerate(cases)
                for arm in (("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline"))
            ],
            "stop_on_first_request_failure": True,
            "replacement_requests": False,
            "structural_repair": False,
            "revision": False,
            "model_judge": False,
            "parameters": copy.deepcopy(PARAMETERS),
            "max_total_output_tokens": 13800,
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
    content = _prepared_path().read_bytes()
    if _sha(content) != expected_prepared_file_sha256:
        raise ComparisonBlocked("prepared_file_sha256_mismatch")
    prepared = json.loads(content)
    if _json_bytes(prepared) != _json_bytes(prepare_bundle()):
        raise ComparisonBlocked("prepared_content_or_source_drift")
    return prepared


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    validator = commands.add_parser("validate")
    validator.add_argument("--expected-prepared-file-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            payload = _json_bytes(prepare_bundle())
            path = _prepared_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            print(json.dumps({"campaign": CAMPAIGN, "prepared_file_sha256": _sha(payload), "model_calls": 0}))
        else:
            validate_prepared(args.expected_prepared_file_sha256)
            print(json.dumps({"campaign": CAMPAIGN, "validated": True, "model_calls": 0}))
    except (ComparisonBlocked, OSError, ValueError, UnicodeError):
        parser.exit(2, "Blocked: preparation_or_validation_failed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
