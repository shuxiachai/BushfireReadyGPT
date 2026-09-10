from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation

from src.report_template import extract_narrative_body
from src.source_attribution import (
    canonical_official_source_ids,
    canonical_rag_source_ids,
    plain_markdown_claim_text,
    strip_application_source_bindings,
    strip_known_attribution_labels,
    visible_markdown_text,
)

GROUNDING_METHOD = "deterministic_lexical_grounding_v4"
DEFAULT_THRESHOLDS = {
    "support_rate": 0.8,
    "citation_coverage_rate": 0.7,
    "citation_precision_rate": 0.8,
    "numeric_consistency_rate": 1.0,
    "maximum_jurisdiction_conflicts": 0,
}

_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "before",
    "but",
    "can",
    "draft",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "must",
    "not",
    "report",
    "should",
    "that",
    "the",
    "their",
    "this",
    "through",
    "use",
    "using",
    "was",
    "were",
    "with",
}
_EVIDENCE_SIGNALS = re.compile(
    r"\b(?:according to|data|dataset|evidence|guidance|indicates?|records?|reports?|source|statistics|shows?)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?%?(?![A-Za-z0-9])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
_JURISDICTION_ALIASES = {
    "Australian Capital Territory": {"australian capital territory", "act"},
    "New South Wales": {"new south wales", "nsw"},
    "Northern Territory": {"northern territory", "nt"},
    "Queensland": {"queensland", "qld"},
    "South Australia": {"south australia"},
    "Tasmania": {"tasmania"},
    "Victoria": {"victoria", "victorian"},
    "Western Australia": {"western australia"},
}
_INDICATOR_LABELS = {
    "population": "community population residents",
    "older_people_pct": "older people residents percentage",
    "no_car_households_pct": "no-car households percentage transport",
    "language_other_than_english_pct": "language other than English at home percentage",
    "language_support_needed": "language support need",
    "matched_sa2_count": "matched SA2 areas count",
    "geography_type": "community geography mapping type",
}
_SNAPSHOT_FIELDS = {
    "community": ("vulnerability_notes",),
    "risk_context": ("risk_points", "assumptions"),
    "plan": ("planning_priorities", "one_week_focus"),
}
_DERIVED_SCALAR_GROUPS = (
    ("community", ("matched_location",), None),
    (
        "community.data_quality",
        ("source_period", "latest_source_year", "source_age_years", "assessed_for_year", "freshness"),
        None,
    ),
    (
        "community.geography_reference.selected_asgs_area",
        (
            "selected_level",
            "selected_area",
            "state_name",
            "sa2_count",
            "sa3_names",
            "sa4_names",
            "gccsa_names",
            "area_albers_sqkm",
        ),
        "asgs_sa2_allocation",
    ),
    ("plan", ("risk_rule_count",), "risk_context_rules"),
)
_UNCERTAIN_OR_REPORTED = re.compile(
    r"\b(?:not|unknown|unverified|user|reported by|hypothetical|example|assum\w*|"
    r"verify|confirm|may|might|could|should|would|about|approximately|around|estimate\w*|target)\b|[\"“”]",
    re.IGNORECASE,
)
_NUMERIC_ASSERTIONS = {
    "population": r"\bpopulation\s*(?:of|is|was|:|=)\s*(?P<value>\d[\d,]*(?:\.\d+)?)\b",
    "older_people_pct": (
        r"\bolder (?:people|residents)(?: percentage)?\s*(?:is|was|:|=|represent|account for)\s*"
        r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*%"
    ),
    "no_car_households_pct": (
        r"\bno-car households?(?: percentage)?\s*(?:is|was|:|=|represent|account for)\s*"
        r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*%"
    ),
    "language_other_than_english_pct": (
        r"\blanguage other than English at home(?: percentage)?\s*(?:is|was|:|=)\s*"
        r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*%"
    ),
}


def evaluate_report_grounding(report_text, analysis, *, thresholds=None):
    """Evaluate auditable evidence alignment; this is not semantic fact verification.

    The method checks model-authored, externally attributable sentences against the
    frozen deterministic analysis and retrieved passages. It deliberately reports
    uncertain claims for human review instead of using an LLM judge.
    """

    active_thresholds = _validate_thresholds(thresholds or DEFAULT_THRESHOLDS)
    analysis_context = analysis if isinstance(analysis, dict) else {}
    narrative = strip_application_source_bindings(
        extract_narrative_body(str(report_text or "")),
        official_sources=(analysis_context.get("data") or {}).get("sources") or [],
        rag_sources=(analysis_context.get("knowledge") or {}).get("retrieved_chunks") or [],
    )
    evidence = _build_evidence_items(analysis_context)
    source_evidence = [item for item in evidence if item["source_id"]]
    claims = []
    for sentence in _sentences(narrative):
        claim_body = _claim_body(sentence, source_evidence)
        if not _WORD.search(claim_body):
            continue
        cited_source_ids = _cited_source_ids(sentence, source_evidence)
        numbers = _numbers(claim_body)
        citation_required = bool(
            cited_source_ids
            or numbers
            or _EVIDENCE_SIGNALS.search(claim_body)
            or _explicit_snapshot_conflicts(claim_body, analysis_context)
        )
        if not citation_required:
            continue
        result = _assess_claim(sentence, claim_body, evidence, cited_source_ids, analysis_context)
        claims.append({"citation_required": True, **result})

    if not claims:
        return {
            "method": GROUNDING_METHOD,
            "status": "not_applicable",
            "review_required": False,
            "thresholds": active_thresholds,
            "metrics": {
                "claims_evaluated": 0,
                "claims_requiring_review": 0,
                "support_rate": None,
                "citation_coverage_rate": None,
                "citation_precision_rate": None,
                "numeric_consistency_rate": None,
                "jurisdiction_conflicts": 0,
            },
            "claims": [],
            "limitations": _limitations(),
        }

    supported = [claim for claim in claims if claim["supported"]]
    cited = [claim for claim in claims if claim["cited_source_ids"]]
    cited_supported = [claim for claim in cited if claim["cited_source_supported"]]
    numeric = [claim for claim in claims if claim["numbers"]]
    numeric_consistent = [claim for claim in numeric if claim["numeric_consistent"]]
    jurisdiction_conflicts = sum(len(claim["jurisdiction_conflicts"]) for claim in claims)
    metrics = {
        "claims_evaluated": len(claims),
        "claims_requiring_review": sum(bool(claim_review_reasons(claim)) for claim in claims),
        "supported_claims": len(supported),
        "support_rate": _rate(len(supported), len(claims)),
        "citation_coverage_rate": _rate(len(cited), len(claims)),
        "citation_precision_rate": _rate(len(cited_supported), len(cited)) if cited else 0.0,
        "numeric_claims": len(numeric),
        "numeric_consistency_rate": _rate(len(numeric_consistent), len(numeric)) if numeric else 1.0,
        "jurisdiction_conflicts": jurisdiction_conflicts,
    }
    passed = (
        metrics["support_rate"] >= active_thresholds["support_rate"]
        and metrics["citation_coverage_rate"] >= active_thresholds["citation_coverage_rate"]
        and metrics["citation_precision_rate"] >= active_thresholds["citation_precision_rate"]
        and metrics["numeric_consistency_rate"] >= active_thresholds["numeric_consistency_rate"]
        and metrics["jurisdiction_conflicts"] <= active_thresholds["maximum_jurisdiction_conflicts"]
        and not any(claim["snapshot_conflicts"] for claim in claims)
    )
    return {
        "method": GROUNDING_METHOD,
        "status": "pass" if passed else "review_required",
        "review_required": not passed,
        "thresholds": active_thresholds,
        "metrics": metrics,
        "claims": claims,
        "limitations": _limitations(),
    }


def grounding_trace_metrics(evaluation):
    """Return only bounded, non-content metrics suitable for an operational trace."""

    metrics = evaluation.get("metrics", {}) if isinstance(evaluation, dict) else {}
    return {
        "grounding_status": evaluation.get("status", "unknown") if isinstance(evaluation, dict) else "unknown",
        "claims_evaluated": int(metrics.get("claims_evaluated") or 0),
        "support_rate": metrics.get("support_rate"),
        "citation_coverage_rate": metrics.get("citation_coverage_rate"),
        "numeric_consistency_rate": metrics.get("numeric_consistency_rate"),
        "jurisdiction_conflicts": int(metrics.get("jurisdiction_conflicts") or 0),
    }


def _validate_thresholds(thresholds):
    required = set(DEFAULT_THRESHOLDS)
    if not isinstance(thresholds, dict) or set(thresholds) != required:
        raise ValueError("Grounding thresholds must declare the complete supported threshold set.")
    result = {}
    for key, value in thresholds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Grounding threshold {key} must be numeric.")
        number = float(value)
        if key == "maximum_jurisdiction_conflicts":
            if not number.is_integer() or number < 0:
                raise ValueError(f"Grounding threshold {key} must be a non-negative integer.")
            result[key] = int(number)
        elif not 0 <= number <= 1:
            raise ValueError(f"Grounding threshold {key} must be between zero and one.")
        else:
            result[key] = number
    return result


def _sentences(text):
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    result = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("|") or re.fullmatch(r"[-| :]+", line):
            continue
        line = re.sub(r"^(?:[-*+] |\d+[.)] )", "", line).strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line):
            value = " ".join(sentence.split()).strip()
            if len(value) >= 20 and _WORD.search(value):
                result.append(value[:600])
    return result


def _build_evidence_items(analysis):
    items = []
    knowledge = analysis.get("knowledge") if isinstance(analysis.get("knowledge"), dict) else {}
    for index, chunk in enumerate(knowledge.get("retrieved_chunks", []) or []):
        if not isinstance(chunk, dict):
            continue
        items.append(
            _evidence_item(
                source_id=str(chunk.get("source_id") or ""),
                title=str(chunk.get("title") or ""),
                agency=str(chunk.get("agency") or ""),
                text=str(chunk.get("text") or ""),
                evidence_type="retrieved_chunk",
                jurisdictions=chunk.get("jurisdictions") or [],
                evidence_path=f"knowledge.retrieved_chunks[{index}].text",
                evidence_version=chunk.get("chunk_sha256") or knowledge.get("index_manifest_sha256"),
            )
        )
    data = analysis.get("data") if isinstance(analysis.get("data"), dict) else {}
    for index, source in enumerate(data.get("sources", []) or []):
        if not isinstance(source, dict):
            continue
        items.append(
            _evidence_item(
                source_id=str(source.get("id") or ""),
                title=str(source.get("name") or ""),
                agency="",
                text=" ".join(str(source.get(key) or "") for key in ("purpose", "use_when")),
                evidence_type="official_source_metadata",
                jurisdictions=[],
                evidence_path=f"data.sources[{index}]",
                evidence_version=_artifact_version(analysis, "official_sources"),
            )
        )
    # Profile/form values, map selections, confidence rows and arbitrary future
    # analysis keys can contain U0 text. Never flatten the entire snapshot.
    community = analysis.get("community") if isinstance(analysis.get("community"), dict) else {}
    indicators = community.get("indicators") if isinstance(community.get("indicators"), dict) else {}
    for key, label in _INDICATOR_LABELS.items():
        value = indicators.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            if key.endswith("_pct") and _decimal_value(value) is not None and not str(value).endswith("%"):
                value = f"{value}%"
            items.append(
                _evidence_item(
                    source_id="",
                    title=label,
                    agency="",
                    text=f"{label}: {value}",
                    evidence_type="deterministic_snapshot",
                    jurisdictions=[],
                    evidence_path=f"community.indicators.{key}",
                    evidence_version=_community_version(analysis),
                )
            )
    for section, fields in _SNAPSHOT_FIELDS.items():
        snapshot = analysis.get(section) if isinstance(analysis.get(section), dict) else {}
        for field in fields:
            values = snapshot.get(field)
            if not isinstance(values, list):
                continue
            for index, value in enumerate(values):
                if not isinstance(value, str) or not value.strip():
                    continue
                items.append(
                    _evidence_item(
                        source_id="",
                        title=field,
                        agency="",
                        text=value,
                        evidence_type="deterministic_snapshot",
                        jurisdictions=[],
                        evidence_path=f"{section}.{field}[{index}]",
                        evidence_version=(
                            _community_version(analysis)
                            if section == "community"
                            else _artifact_version(analysis, "risk_context_rules")
                            if section == "risk_context"
                            else None
                        ),
                    )
                )
    # Preserve known computed geography/vintage facts without admitting unknown
    # children or raw form/selection copies next to them.
    for path, fields, artifact in _DERIVED_SCALAR_GROUPS:
        snapshot = analysis
        for component in path.split("."):
            snapshot = snapshot.get(component) if isinstance(snapshot, dict) else None
        if not isinstance(snapshot, dict):
            continue
        for field in fields:
            value = snapshot.get(field)
            if not isinstance(value, (str, int, float)) or isinstance(value, bool) or not str(value).strip():
                continue
            label = field.replace("_", " ")
            items.append(
                _evidence_item(
                    source_id="",
                    title=label,
                    agency="",
                    text=f"{label}: {value}",
                    evidence_type="deterministic_snapshot",
                    jurisdictions=[],
                    evidence_path=f"{path}.{field}",
                    evidence_version=_artifact_version(analysis, artifact)
                    if artifact
                    else _community_version(analysis),
                )
            )
    return items


def _artifact_version(analysis, key):
    provenance = analysis.get("data_provenance")
    entry = provenance.get(key) if isinstance(provenance, dict) else None
    value = entry.get("sha256") if isinstance(entry, dict) else None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _community_version(analysis):
    if analysis.get("area_selection"):
        return _artifact_version(analysis, "all_sa2_profile")
    return _artifact_version(analysis, "community_profile") or _artifact_version(analysis, "community_sample")


def _evidence_item(
    *, source_id, title, agency, text, evidence_type, jurisdictions, evidence_path, evidence_version=None
):
    return {
        "source_id": source_id,
        "title": title,
        "agency": agency,
        "text": text,
        "evidence_type": evidence_type,
        "evidence_path": evidence_path,
        "evidence_version": evidence_version,
        "evidence_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "jurisdictions": [str(value) for value in jurisdictions],
        # Source titles and agency names identify a citation; they are not
        # substantive support for the surrounding factual claim.
        "tokens": _tokens(text),
        "numbers": _numbers(text),
    }


def _assess_claim(sentence, claim_body, evidence, cited_source_ids, analysis):
    claim_tokens = _tokens(claim_body)
    claim_numbers = _numbers(claim_body)
    ranked = []
    for item in evidence:
        overlap = claim_tokens & item["tokens"]
        score = len(overlap) / max(1, min(len(claim_tokens), 12))
        numbers_match = not claim_numbers or claim_numbers.issubset(item["numbers"])
        ranked.append((score, len(overlap), numbers_match, item))
    ranked.sort(key=lambda row: (row[0], row[1], row[3]["source_id"]), reverse=True)
    best = ranked[0] if ranked else (0.0, 0, not claim_numbers, None)
    supported = bool(best[3]) and best[1] >= 2 and best[0] >= 0.25 and best[2]
    all_evidence_numbers = set().union(*(item["numbers"] for item in evidence)) if evidence else set()
    numeric_consistent = not claim_numbers or claim_numbers.issubset(all_evidence_numbers)
    cited_matches = [
        row for row in ranked if row[3]["source_id"] in cited_source_ids and row[1] >= 2 and row[0] >= 0.25 and row[2]
    ]
    conflicts = _jurisdiction_conflicts(claim_body, analysis, evidence)
    snapshot_conflicts = _explicit_snapshot_conflicts(claim_body, analysis)
    claim_hash = hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]
    return {
        "claim_id": claim_hash,
        "claim": sentence,
        "supported": supported and numeric_consistent and not conflicts and not snapshot_conflicts,
        "support_score": round(best[0], 4),
        "best_evidence_type": best[3]["evidence_type"] if best[3] else None,
        "best_evidence_source_id": best[3]["source_id"] if best[3] else None,
        "best_evidence_path": best[3]["evidence_path"] if best[3] else None,
        "best_evidence_version": best[3]["evidence_version"] if best[3] else None,
        "best_evidence_sha256": best[3]["evidence_sha256"] if best[3] else None,
        "cited_source_ids": sorted(cited_source_ids),
        "cited_source_supported": bool(cited_matches),
        "numbers": sorted(claim_numbers),
        "numeric_consistent": numeric_consistent,
        "jurisdiction_conflicts": conflicts,
        "snapshot_conflicts": snapshot_conflicts,
    }


def claim_review_reasons(claim):
    """One issue selector for new evaluations and older report-bound UI snapshots."""

    reasons = []
    if claim.get("snapshot_conflicts"):
        reasons.append("explicit statement conflicts with the frozen snapshot; correct or reanalyse before approval")
    if claim.get("numeric_consistent") is False:
        reasons.append("number not found in frozen trusted evidence (not proof of a false claim)")
    if claim.get("jurisdiction_conflicts"):
        reasons.append("jurisdiction reference needs review")
    if claim.get("citation_required", True) and not claim.get("cited_source_ids"):
        reasons.append("no recognised source attribution")
    elif claim.get("cited_source_ids") and claim.get("cited_source_supported") is not True:
        reasons.append("cited source does not support this claim under the lexical check")
    if claim.get("supported") is not True:
        reasons.append("insufficient lexical evidence alignment")
    return reasons


def _decimal_value(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = Decimal(str(value).replace(",", "").rstrip("%"))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _explicit_snapshot_conflicts(claim, analysis):
    """Identify narrow snapshot contradictions, not unknown or semantic truth.

    Unmatched numbers, quotes, estimates, comparisons and generic mentions of a
    different state remain review diagnostics rather than approval blockers.
    """

    # Visible emphasis must not hide the value. Scope qualifiers to individual
    # assertions, so a separate contact-list instruction neither excuses an
    # earlier conflicting population nor turns a school count into community data.
    visible = plain_markdown_claim_text(visible_markdown_text(claim))
    units = re.split(
        r"\s*;\s*|\s*,?\s+\b(?:and|but|while|whereas|compared with|in contrast to)\b\s+", visible, flags=re.IGNORECASE
    )
    return [conflict for unit in units for conflict in _snapshot_unit_conflicts(unit.strip(" ,"), analysis)]


def _snapshot_unit_conflicts(claim, analysis):
    if _UNCERTAIN_OR_REPORTED.search(claim):
        return []
    conflicts = []
    community = analysis.get("community") if isinstance(analysis.get("community"), dict) else {}
    indicators = community.get("indicators") if isinstance(community.get("indicators"), dict) else {}
    if re.search(
        r"\b(?:community data|community profile|selected area|matched community|community population)\b", claim, re.I
    ):
        for field, pattern in _NUMERIC_ASSERTIONS.items():
            expected = _decimal_value(indicators.get(field))
            if expected is None or (field.endswith("_pct") and expected > 100):
                continue
            for match in re.finditer(pattern, claim, re.IGNORECASE):
                prefix = claim[: match.start()]
                if not re.search(
                    r"\b(?:community data|community profile|selected area|matched community|community)\b", prefix, re.I
                ):
                    continue
                if field == "population" and not re.search(
                    r"\b(?:community|data|profile|area|a|the|total|recorded|shows?|records?|indicates?|has|with)\s*$",
                    prefix,
                    re.I,
                ):
                    continue
                observed = _decimal_value(match.group("value"))
                if observed is not None and observed != expected:
                    conflicts.append(
                        {
                            "kind": "numeric_snapshot_conflict",
                            "evidence_path": f"community.indicators.{field}",
                            "expected": str(expected),
                            "observed": str(observed),
                        }
                    )
    profile = analysis.get("profile") if isinstance(analysis.get("profile"), dict) else {}
    expected_state = profile.get("state")
    if expected_state in _JURISDICTION_ALIASES:
        match = re.search(
            r"\b(?:report|planning|selected|primary|current) jurisdiction\s*(?:is|:|=)\s*(?P<state>[^.;!?]+)",
            claim,
            re.IGNORECASE,
        )
        if match:
            stated = match.group("state").strip().casefold()
            for state, aliases in _JURISDICTION_ALIASES.items():
                if stated in aliases and state != expected_state:
                    conflicts.append(
                        {
                            "kind": "jurisdiction_snapshot_conflict",
                            "evidence_path": "profile.state",
                            "expected": expected_state,
                            "observed": state,
                        }
                    )
    return conflicts


def _cited_source_ids(sentence, evidence):
    rag_sources, official_sources = _attribution_sources(evidence)
    return canonical_rag_source_ids(sentence, rag_sources) | canonical_official_source_ids(
        sentence,
        official_sources,
    )


def _claim_body(sentence, evidence):
    rag_sources, official_sources = _attribution_sources(evidence)
    return strip_known_attribution_labels(
        sentence,
        rag_sources=rag_sources,
        official_sources=official_sources,
    )


def _attribution_sources(evidence):
    rag_sources = [
        {
            "source_id": item["source_id"],
            "title": item["title"],
        }
        for item in evidence
        if item["evidence_type"] == "retrieved_chunk"
    ]
    official_sources = [
        {
            "id": item["source_id"],
            "name": item["title"],
        }
        for item in evidence
        if item["evidence_type"] == "official_source_metadata"
    ]
    return rag_sources, official_sources


def _jurisdiction_conflicts(sentence, analysis, evidence):
    profile = analysis.get("profile") if isinstance(analysis.get("profile"), dict) else {}
    expected = str(profile.get("state") or "")
    if expected not in _JURISDICTION_ALIASES:
        return []
    allowed = {expected}
    for item in evidence:
        allowed.update(value for value in item["jurisdictions"] if value in _JURISDICTION_ALIASES)
    lowered = sentence.lower()
    conflicts = []
    for jurisdiction, aliases in _JURISDICTION_ALIASES.items():
        if jurisdiction in allowed:
            continue
        mentioned = any(
            re.search(rf"(?<![A-Za-z]){re.escape(alias.upper())}(?![A-Za-z])", sentence)
            if alias in {"act", "nsw", "nt", "qld"}
            else re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered)
            for alias in aliases
        )
        if mentioned:
            conflicts.append(jurisdiction)
    return sorted(conflicts)


def _tokens(value):
    return {word.lower() for word in _WORD.findall(str(value or "")) if word.lower() not in _STOP_WORDS}


def _numbers(value):
    return {match.group(0).replace(",", "") for match in _NUMBER.finditer(str(value or "")) if match.group(0) != "000"}


def _rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else 1.0


def _limitations():
    return [
        "This deterministic lexical check measures alignment with the frozen evidence snapshot; it does not prove truth or currency.",
        "Paraphrases can be missed and matching words do not establish semantic entailment.",
        "Only explicit processed-data and application-derived fields are support evidence; raw U0 inputs are excluded.",
        "Snapshot conflicts cover narrow explicit statements only; unmatched numbers or state mentions are not proof of factual error.",
        "Every flagged or passing claim still requires human review against the cited current official page.",
    ]
