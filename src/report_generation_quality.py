from __future__ import annotations

import re

from src.agents.report_quality_agent import ReportQualityAgent
from src.report_template import (
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
)

MAX_REPORT_REPAIR_ATTEMPTS = 2
_JURISDICTION_NAMES = (
    "Australian Capital Territory",
    "New South Wales",
    "Northern Territory",
    "South Australia",
    "Western Australia",
    "Queensland",
    "Tasmania",
    "Victoria",
    "Australia",
)


def normalize_generated_narrative(narrative):
    """Normalise checklist bullet syntax without changing report meaning."""

    lines = str(narrative or "").splitlines()
    in_checklist = False
    checklist_level = None
    result = []
    for line in lines:
        heading = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = re.sub(r"^\d+[.)]\s*", "", heading.group(2).strip()).lower()
            if title == "human review and approval checklist":
                in_checklist = True
                checklist_level = level
            elif in_checklist and level <= checklist_level:
                in_checklist = False
                checklist_level = None
            result.append(line)
            continue
        if in_checklist:
            bullet = re.match(r"^(\s*)[-*]\s+(?!\[[ xX]\]\s*)(?:\[\s*\]\s*)?(.+)$", line)
            numbered = re.match(r"^(\s*)\d+[.)]\s+(.+)$", line)
            if bullet:
                line = f"{bullet.group(1)}- [ ] {bullet.group(2).strip()}"
            elif numbered:
                line = f"{numbered.group(1)}- [ ] {numbered.group(2).strip()}"
        result.append(line)
    return "\n".join(result)


def _agency_acronyms(agency):
    value = str(agency or "").strip()
    variants = {value}
    for jurisdiction in _JURISDICTION_NAMES:
        variants.add(re.sub(re.escape(jurisdiction), "", value, flags=re.IGNORECASE).strip(" ,-/"))
    acronyms = set()
    for variant in variants:
        words = [
            word
            for word in re.findall(r"[A-Za-z]+", variant)
            if word.lower() not in {"and", "of", "the"}
        ]
        acronym = "".join(word[0].upper() for word in words)
        if len(acronym) >= 3:
            acronyms.add(acronym)
    return acronyms


def attributed_rag_source_ids(narrative, chunks):
    text = str(narrative or "")
    lowered = text.lower()
    attributed = set()
    for chunk in chunks or []:
        title = str(chunk.get("title") or "").strip()
        agency = str(chunk.get("agency") or "").strip()
        exact_match = any(value and value.lower() in lowered for value in (title, agency))
        acronym_match = any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(acronym)}(?![A-Za-z0-9])", text, re.IGNORECASE)
            for acronym in _agency_acronyms(agency)
        )
        if exact_match or acronym_match:
            attributed.add(chunk.get("source_id"))
    return attributed


def _append_rag_attribution_check(quality, narrative, analysis):
    chunks = (analysis.get("knowledge") or {}).get("retrieved_chunks") or []
    source_values = {
        str(value).strip()
        for chunk in chunks
        for value in (chunk.get("title"), chunk.get("agency"))
        if str(value or "").strip()
    }
    if not source_values:
        return quality
    attributed_ids = attributed_rag_source_ids(narrative, chunks)
    passed = bool(attributed_ids)
    check = {
        "status": "pass" if passed else "fail",
        "name": "RAG source attribution",
        "detail": (
            "The narrative attributes retrieved official source(s): " + ", ".join(sorted(attributed_ids))
            if passed
            else "Name at least one retrieved source title, agency or recognised agency acronym in Data Sources and Limitations."
        ),
    }
    quality["checks"].append(check)
    quality["summary"]["total"] += 1
    quality["summary"]["passed" if passed else "failed"] += 1
    if not passed:
        failure = {"name": check["name"], "detail": check["detail"]}
        quality["approval_gate"]["blocking_failures"].append(failure)
        quality["approval_gate"]["passed"] = False
        quality["approval_gate"]["status"] = "blocked"
    return quality


def assess_generated_narrative(narrative, analysis):
    """Run the exact structural gate against a provisional governed report."""

    narrative = normalize_generated_narrative(narrative)
    report = apply_governance_notice(narrative)
    report = append_evidence_tables(report, analysis)
    report = append_human_signoff(report, {"report_status": "Draft - human review required"})
    quality = ReportQualityAgent().run(report)
    return _append_rag_attribution_check(quality, narrative, analysis)


def build_report_repair_prompt(original_prompt, previous_response, quality):
    failures = quality.get("approval_gate", {}).get("blocking_failures", [])
    failure_lines = "\n".join(
        f"- {item.get('name')}: {item.get('detail')}" for item in failures if isinstance(item, dict)
    )
    previous_character_count = len(str(previous_response or ""))
    return f"""The previous draft failed deterministic structural checks.

Blocking checks:
{failure_lines or "- Complete every required section with substantive content."}

Return one complete replacement report. Do not return a patch, explanation, preface, JSON or only appendices.
Keep every safety, evidence and human-review boundary in the original instructions. Include an explicit Day 1,
today or first-24-hours action and do not describe any candidate assembly location as confirmed safe.
For every section reported as missing or insufficient, include at least one complete, section-specific sentence
or a concrete list/table with multiple decision-useful items. Never leave a required heading followed only by
subheadings or placeholder labels.

The previous {previous_character_count}-character response is intentionally omitted so the replacement request
fits within the local model context window. Rebuild the complete report from the governed request below.

Original governed report request:
{original_prompt}
"""
