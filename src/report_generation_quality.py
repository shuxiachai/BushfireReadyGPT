from __future__ import annotations

from src.agents.report_quality_agent import ReportQualityAgent
from src.report_template import (
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
)


def assess_generated_narrative(narrative, analysis):
    """Run the exact structural gate against a provisional governed report."""

    report = apply_governance_notice(narrative)
    report = append_evidence_tables(report, analysis)
    report = append_human_signoff(report, {"report_status": "Draft - human review required"})
    return ReportQualityAgent().run(report)


def build_report_repair_prompt(original_prompt, previous_response, quality):
    failures = quality.get("approval_gate", {}).get("blocking_failures", [])
    failure_lines = "\n".join(
        f"- {item.get('name')}: {item.get('detail')}" for item in failures if isinstance(item, dict)
    )
    return f"""The previous draft failed deterministic structural checks.

Blocking checks:
{failure_lines or "- Complete every required section with substantive content."}

Return one complete replacement report. Do not return a patch, explanation, preface, JSON or only appendices.
Keep every safety, evidence and human-review boundary in the original instructions. Include an explicit Day 1,
today or first-24-hours action and do not describe any candidate assembly location as confirmed safe.

Original governed report request:
{original_prompt}

Previous incomplete response to replace:
{previous_response}
"""
