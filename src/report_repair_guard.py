"""Content-free comparison of successive drafts; separate from acceptance policy."""

from dataclasses import dataclass

from src.model_response import ModelServiceError

REPAIR_GUARD_RULESET = "report-repair-guard-v2"
REPAIR_FINDING_CODES = {
    "Processed community provenance": frozenset(
        {
            "p2_unknown_measurement_omitted",
            "p2_unknown_measurement_promoted",
            "p2_invalid_frozen_measurement",
            "p2_available_fact_omitted",
            "p2_value_mismatch",
            "p2_adjacent_provenance_missing",
            "p2_period_missing",
            "p2_geographic_basis_missing",
            "p2_aggregation_limit_missing",
            "p2_community_not_campus_scope_missing",
        }
    ),
    "Local proposal attribution": frozenset(
        {"local_task_requires_own_proposal_and_confirmer", "proposal_confirmer_missing"}
    ),
    "Rule-derived causal qualification": frozenset(
        {
            "causal_planning_inference_unqualified",
            "r3_inference_cannot_borrow_official_citation",
            "unsupported_causal_effect_assertion",
        }
    ),
    "Submitted passage scope and conflicts": frozenset(
        {
            "cited_passage_not_final_submitted",
            "physical_assembly_criteria_require_authority_verification",
            "household_source_scope_not_preserved",
            "contradictory_source_used_as_advice",
        }
    ),
}
REQUIRED_REPAIR_CHECKS = frozenset(
    {
        "Substantive narrative",
        "Required sections",
        "Official sources",
        "Safety disclaimer",
        "Emergency number 000",
        "Action plan",
        "Checklist",
        "Roles and responsibilities",
        "Assembly point wording",
        "Safety boundary assertions",
        "Model-authored URLs",
        "Model-authored raw HTML",
        "Unverified attribution markers",
        "Evidence tables",
        "Evidence confidence",
        "Human review status",
        "Application-owned section protocol",
        "Model prose word budget",
        "Application-owned report fields",
        "Narrative word budget",
        "Processed community provenance",
        "Local proposal attribution",
        "Rule-derived causal qualification",
        "Submitted passage scope and conflicts",
    }
)
_KNOWN_CHECKS = REQUIRED_REPAIR_CHECKS | {
    "Selected scenario coverage",
    "Selected focus-area coverage",
    "RAG source attribution",
}
_CHECK_IDS = {
    "Substantive narrative": "substantive_narrative",
    "Required sections": "required_sections",
    "Official sources": "official_sources",
    "Safety disclaimer": "safety_disclaimer",
    "Emergency number 000": "emergency_number_000",
    "Action plan": "action_plan",
    "Checklist": "checklist",
    "Roles and responsibilities": "roles_and_responsibilities",
    "Assembly point wording": "assembly_point_wording",
    "Safety boundary assertions": "safety_boundary_assertions",
    "Model-authored URLs": "model_authored_urls",
    "Model-authored raw HTML": "model_authored_raw_html",
    "Unverified attribution markers": "unverified_attribution_markers",
    "Evidence tables": "evidence_tables",
    "Evidence confidence": "evidence_confidence",
    "Human review status": "human_review_status",
    "Application-owned section protocol": "application_owned_section_protocol",
    "Model prose word budget": "model_prose_word_budget",
    "Application-owned report fields": "application_owned_report_fields",
    "Narrative word budget": "narrative_word_budget",
    "Processed community provenance": "processed_community_provenance",
    "Local proposal attribution": "local_proposal_attribution",
    "Rule-derived causal qualification": "rule_derived_causal_qualification",
    "Submitted passage scope and conflicts": "submitted_passage_scope_and_conflicts",
    "Selected scenario coverage": "selected_scenario_coverage",
    "Selected focus-area coverage": "selected_focus_area_coverage",
    "RAG source attribution": "rag_source_attribution",
}
_STATUS_RANK = {status: rank for rank, status in enumerate(("fail", "warning", "pass"))}
_WORD_CHECKS = ("Narrative word budget", "Model prose word budget")
_REASONS = {
    "invalid_quality_snapshot",
    "check_status_regressed",
    "word_budget_distance_increased",
    "content_finding_count_increased",
    "repeated_failed_draft",
}


class ReportRepairRegressionError(ModelServiceError):
    """Stop the generation transaction without retaining any response content."""

    code = "report_repair_regression"
    ruleset = REPAIR_GUARD_RULESET

    def __init__(
        self,
        *,
        baseline_attempt_number,
        candidate_attempt_number,
        reason,
        regressed_checks=(),
        worsened_budgets=(),
        worsened_findings=(),
    ):
        if (
            type(baseline_attempt_number) is not int
            or type(candidate_attempt_number) is not int
            or not 1 <= baseline_attempt_number < candidate_attempt_number <= 3
        ):
            raise ValueError("Repair-stop attempts must be ordered integers within the three-call ceiling.")
        self.baseline_attempt_number = baseline_attempt_number
        self.candidate_attempt_number = candidate_attempt_number
        self.reason = reason if isinstance(reason, str) and reason in _REASONS else "invalid_quality_snapshot"
        self.regressed_check_ids = tuple(
            sorted({_CHECK_IDS[name] for name in regressed_checks if isinstance(name, str) and name in _KNOWN_CHECKS})
        )
        self.worsened_word_budget_ids = tuple(
            sorted({_CHECK_IDS[name] for name in worsened_budgets if isinstance(name, str) and name in _WORD_CHECKS})
        )
        self.worsened_finding_check_ids = tuple(
            sorted(
                {
                    _CHECK_IDS[name]
                    for name in worsened_findings
                    if isinstance(name, str) and name in REPAIR_FINDING_CODES
                }
            )
        )
        explanation = {
            "invalid_quality_snapshot": "the repair comparison could not be validated",
            "content_finding_count_increased": "a repair increased a mandatory content finding count",
            "repeated_failed_draft": "a repair repeated a complete draft that still fails the approval gate",
        }.get(self.reason, "a repair regressed from the previous draft")
        super().__init__(
            f"Report generation stopped because {explanation}. "
            "No new report was saved; any existing report is unchanged. Retry generation."
        )


@dataclass(frozen=True)
class RepairAssessment:
    """Only immutable application-owned status/count data may survive a callback."""

    statuses: tuple[tuple[str, int], ...]
    word_counts: tuple[int, int]
    finding_counts: tuple[tuple[str, str, int], ...]
    valid: bool
    invalid_checks: tuple[str, ...]


def _word_count(check, name):
    count = check.get("word_count")
    if type(count) is not int or not 0 <= count <= 100_000:
        return None
    expected_pass = 650 <= count <= 800 if name == "Narrative word budget" else count >= 300
    if check.get("status") != ("pass" if expected_pass else "fail"):
        return None
    if name == "Narrative word budget" and any(
        key in check and (type(check[key]) is not int or check[key] != value)
        for key, value in (("minimum", 650), ("maximum", 800))
    ):
        return None
    return count


def _finding_counts(check, name):
    findings = check.get("findings")
    if not isinstance(findings, list):
        return None
    counts = {}
    for finding in findings:
        if not isinstance(finding, dict):
            return None
        code, count = finding.get("code"), finding.get("count")
        if (
            not isinstance(code, str)
            or code not in REPAIR_FINDING_CODES[name]
            or code in counts
            or type(count) is not int
            or not 1 <= count <= 100_000
        ):
            return None
        counts[code] = count
    if check.get("status") != ("fail" if counts else "pass"):
        return None
    return tuple((name, code, counts.get(code, 0)) for code in sorted(REPAIR_FINDING_CODES[name]))


def snapshot_repair_assessment(quality):
    """Capture an invalid sentinel instead of changing first-draft behavior."""
    checks = quality.get("checks") if isinstance(quality, dict) else None
    if not isinstance(checks, list):
        return RepairAssessment((), (0, 0), (), False, ())
    statuses, counts, finding_counts, invalid_checks = {}, {}, [], set()
    valid = True
    for check in checks:
        if not isinstance(check, dict):
            valid = False
            continue
        name = check.get("name")
        if not isinstance(name, str) or name not in _KNOWN_CHECKS:
            valid = False
            continue
        status = check.get("status")
        if name in statuses or not isinstance(status, str) or status not in _STATUS_RANK:
            invalid_checks.add(name)
            valid = False
        statuses[name] = _STATUS_RANK.get(status, -1) if isinstance(status, str) else -1
        if name in REPAIR_FINDING_CODES:
            content_counts = _finding_counts(check, name)
            if content_counts is None:
                invalid_checks.add(name)
                valid = False
            else:
                finding_counts.extend(content_counts)
        if name in _WORD_CHECKS:
            count = _word_count(check, name)
            if count is None:
                invalid_checks.add(name)
                valid = False
            else:
                counts[name] = count
    missing = REQUIRED_REPAIR_CHECKS - statuses.keys()
    invalid_checks.update(missing)
    return RepairAssessment(
        tuple(sorted(statuses.items())),
        tuple(counts.get(name, 0) for name in _WORD_CHECKS),
        tuple(sorted(finding_counts)),
        valid and not missing,
        tuple(sorted(invalid_checks)),
    )


def reject_repair_regression(previous, candidate, *, baseline_attempt_number, candidate_attempt_number):
    """Reject status downgrades, increased budget distance or mandatory finding counts."""
    previous_statuses, candidate_statuses = dict(previous.statuses), dict(candidate.statuses)
    changed_names = previous_statuses.keys() ^ candidate_statuses.keys()
    if not previous.valid or not candidate.valid or changed_names:
        raise ReportRepairRegressionError(
            baseline_attempt_number=baseline_attempt_number,
            candidate_attempt_number=candidate_attempt_number,
            reason="invalid_quality_snapshot",
        )
    regressed = {name for name, rank in previous_statuses.items() if candidate_statuses[name] < rank}
    previous_total, previous_model = previous.word_counts
    candidate_total, candidate_model = candidate.word_counts
    worsened_budgets = set()
    if max(650 - candidate_total, candidate_total - 800, 0) > max(650 - previous_total, previous_total - 800, 0):
        worsened_budgets.add("Narrative word budget")
    if max(300 - candidate_model, 0) > max(300 - previous_model, 0):
        worsened_budgets.add("Model prose word budget")
    previous_findings = {(name, code): count for name, code, count in previous.finding_counts}
    worsened_findings = {
        name for name, code, count in candidate.finding_counts if count > previous_findings[(name, code)]
    }
    if regressed or worsened_budgets or worsened_findings:
        raise ReportRepairRegressionError(
            baseline_attempt_number=baseline_attempt_number,
            candidate_attempt_number=candidate_attempt_number,
            reason=(
                "check_status_regressed"
                if regressed
                else "word_budget_distance_increased"
                if worsened_budgets
                else "content_finding_count_increased"
            ),
            regressed_checks=regressed,
            worsened_budgets=worsened_budgets,
            worsened_findings=worsened_findings,
        )
