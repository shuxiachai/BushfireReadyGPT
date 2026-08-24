from __future__ import annotations

import hashlib
import json
import re

from src.agents.report_quality_agent import ReportQualityAgent
from src.report_template import (
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
    extract_narrative_body,
)

MAX_REPORT_REPAIR_ATTEMPTS = 2
CURRENT_POLICY = "governed-report-v2"
QUALITY_POLICY_VERSION = CURRENT_POLICY  # Backwards-compatible public alias.


def _policy_fingerprint(manifest):
    return hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


# Keep every fingerprinted manifest here after it stops being current. This is
# the compatibility registry used to verify old audit chains without making
# those policy bindings eligible for a new review or export transition.
KNOWN_QUALITY_POLICY_MANIFESTS = {
    "governed-report-v2": {
        "fingerprint_schema": "quality-policy-manifest-v1",
        "policy_version": "governed-report-v2",
        "structural_ruleset": "report-quality-agent-v2",
        "safety_boundary_ruleset": "safety-boundary-v2",
        "rag_attribution_ruleset": "rag-attribution-v1",
    },
}
_KNOWN_POLICY_FINGERPRINTS = {
    version: _policy_fingerprint(manifest) for version, manifest in KNOWN_QUALITY_POLICY_MANIFESTS.items()
}
QUALITY_POLICY_MANIFEST = KNOWN_QUALITY_POLICY_MANIFESTS[CURRENT_POLICY]
QUALITY_POLICY_FINGERPRINT = _KNOWN_POLICY_FINGERPRINTS[CURRENT_POLICY]

# Unversioned v4 events, governed-report-v1, and early v2 events did not carry
# implementation fingerprints. They remain readable only at those exact
# version/fingerprint combinations.
_UNFINGERPRINTED_POLICY_VERSIONS = frozenset({None, "governed-report-v1", "governed-report-v2"})
READABLE_QUALITY_POLICY_BINDINGS = {
    None: frozenset({None}),
    "governed-report-v1": frozenset({None}),
    **{
        version: frozenset({fingerprint, *({None} if version in _UNFINGERPRINTED_POLICY_VERSIONS else set())})
        for version, fingerprint in _KNOWN_POLICY_FINGERPRINTS.items()
    },
}
SUPPORTED_HISTORICAL_POLICIES = frozenset(
    version for version in READABLE_QUALITY_POLICY_BINDINGS if version != CURRENT_POLICY
)
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
        words = [word for word in re.findall(r"[A-Za-z]+", variant) if word.lower() not in {"and", "of", "the"}]
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
    """Run the canonical governed gate against a provisional report."""

    narrative = normalize_generated_narrative(narrative)
    report = apply_governance_notice(narrative)
    report = append_evidence_tables(report, analysis)
    report = append_human_signoff(report, {"report_status": "Draft - human review required"})
    return evaluate_governed_report(report, analysis)


def generate_narrative_with_repairs(
    original_prompt,
    analysis,
    generate_attempt,
    *,
    max_repair_attempts=MAX_REPORT_REPAIR_ATTEMPTS,
):
    """Generate and deterministically repair one governed narrative.

    ``generate_attempt`` receives ``(prompt, attempt_number, is_repair)``. Keeping
    provider calls behind this callback lets the application attach tracing while
    evaluations use the exact same repair policy without duplicating the loop.
    """

    if not callable(generate_attempt):
        raise TypeError("generate_attempt must be callable.")
    if isinstance(max_repair_attempts, bool) or not isinstance(max_repair_attempts, int) or max_repair_attempts < 0:
        raise ValueError("max_repair_attempts must be a non-negative integer.")

    attempt_count = 1
    narrative = normalize_generated_narrative(generate_attempt(original_prompt, attempt_count, False))
    quality = assess_generated_narrative(narrative, analysis)
    for _ in range(max_repair_attempts):
        if quality.get("approval_gate", {}).get("passed") is True:
            break
        repair_prompt = build_report_repair_prompt(original_prompt, narrative, quality)
        attempt_count += 1
        narrative = normalize_generated_narrative(generate_attempt(repair_prompt, attempt_count, True))
        quality = assess_generated_narrative(narrative, analysis)
    return narrative, quality, attempt_count


def evaluate_governed_report(report_text, analysis):
    """Run the canonical deterministic gate used by every governed lifecycle stage.

    RAG attribution is evaluated only against the model-authored narrative. The
    deterministic evidence appendix contains source titles by construction and
    must never be able to make an unattributed narrative pass.
    """

    report = str(report_text or "")
    quality = ReportQualityAgent().run(report)
    narrative = extract_narrative_body(report)
    quality = _append_rag_attribution_check(quality, narrative, analysis or {})
    quality["quality_policy_version"] = CURRENT_POLICY
    quality["quality_policy_fingerprint"] = QUALITY_POLICY_FINGERPRINT
    return quality


def quality_policy_metadata():
    """Return a detached, serialisable identity for the canonical gate."""

    return {
        "version": CURRENT_POLICY,
        "fingerprint": QUALITY_POLICY_FINGERPRINT,
        "manifest": dict(QUALITY_POLICY_MANIFEST),
    }


def is_current_quality_policy_binding(version, fingerprint):
    """Return whether an audit/quality result uses the exact current policy."""

    return version == CURRENT_POLICY and fingerprint == QUALITY_POLICY_FINGERPRINT


def is_readable_quality_policy_binding(version, fingerprint):
    """Return whether a historical or current policy binding can be verified."""

    try:
        readable_fingerprints = READABLE_QUALITY_POLICY_BINDINGS.get(version)
    except TypeError:
        return False
    return readable_fingerprints is not None and fingerprint in readable_fingerprints


def build_report_repair_prompt(original_prompt, previous_response, quality):
    failures = quality.get("approval_gate", {}).get("blocking_failures", [])
    failure_lines = "\n".join(
        f"- {item.get('name')}: {item.get('detail')}" for item in failures if isinstance(item, dict)
    )
    previous_character_count = len(str(previous_response or ""))
    return f"""The previous draft failed the deterministic governed quality checks.

Blocking checks:
{failure_lines or "- Complete every required section with substantive content."}

Return one complete replacement report. Do not return a patch, explanation, preface, JSON or only appendices.
Keep every safety, evidence and human-review boundary in the original instructions. Include an explicit Day 1,
today or first-24-hours action. Treat every assembly point, evacuation centre, shelter, refuge, hall, school,
gym, library, oval, sports field, car park, building and site as an unverified candidate. Never state that one
of those places is, remains or has been safe, open, approved, authorised, available, operational, suitable or
cleared, and never state that it will serve as an evacuation or assembly location. Instead say that each option
is a candidate pending current verification by the responsible authority and organisational approval. Apply
this rewrite everywhere in the replacement, including tables, checklists and examples; do not quote an unsafe
claim merely to reject it.
For every section reported as missing or insufficient, include at least one complete, section-specific sentence
or a concrete list/table with multiple decision-useful items. Never leave a required heading followed only by
subheadings or placeholder labels.

The previous {previous_character_count}-character response is intentionally omitted so the replacement request
fits within the local model context window. Rebuild the complete report from the governed request below.

Original governed report request:
{original_prompt}
"""
