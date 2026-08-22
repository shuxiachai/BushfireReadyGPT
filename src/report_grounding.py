from __future__ import annotations

import hashlib
import re

from src.report_template import extract_narrative_body

GROUNDING_METHOD = "deterministic_lexical_grounding_v1"
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


def evaluate_report_grounding(report_text, analysis, *, thresholds=None):
    """Evaluate auditable evidence alignment; this is not semantic fact verification.

    The method checks model-authored, externally attributable sentences against the
    frozen deterministic analysis and retrieved passages. It deliberately reports
    uncertain claims for human review instead of using an LLM judge.
    """

    active_thresholds = _validate_thresholds(thresholds or DEFAULT_THRESHOLDS)
    narrative = extract_narrative_body(str(report_text or ""))
    evidence = _build_evidence_items(analysis if isinstance(analysis, dict) else {})
    source_evidence = [item for item in evidence if item["source_id"]]
    claims = []
    for sentence in _sentences(narrative):
        cited_source_ids = _cited_source_ids(sentence, source_evidence)
        numbers = _numbers(sentence)
        citation_required = bool(cited_source_ids or numbers or _EVIDENCE_SIGNALS.search(sentence))
        if not citation_required:
            continue
        result = _assess_claim(sentence, evidence, cited_source_ids, analysis)
        claims.append({"citation_required": True, **result})

    if not claims:
        return {
            "method": GROUNDING_METHOD,
            "status": "not_applicable",
            "review_required": False,
            "thresholds": active_thresholds,
            "metrics": {
                "claims_evaluated": 0,
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
    for chunk in knowledge.get("retrieved_chunks", []) or []:
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
            )
        )
    data = analysis.get("data") if isinstance(analysis.get("data"), dict) else {}
    for source in data.get("sources", []) or []:
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
            )
        )
    for key, value in analysis.items():
        if key in {"knowledge", "data", "prompt_context", "resolved_data_paths", "data_provenance"}:
            continue
        flattened = " ".join(_scalar_values(value))
        if flattened:
            items.append(
                _evidence_item(
                    source_id="",
                    title=str(key),
                    agency="",
                    text=flattened,
                    evidence_type="deterministic_snapshot",
                    jurisdictions=[],
                )
            )
    return items


def _evidence_item(*, source_id, title, agency, text, evidence_type, jurisdictions):
    combined = " ".join(value for value in (title, agency, text) if value)
    return {
        "source_id": source_id,
        "title": title,
        "agency": agency,
        "text": text,
        "evidence_type": evidence_type,
        "jurisdictions": [str(value) for value in jurisdictions],
        "tokens": _tokens(combined),
        "numbers": _numbers(combined),
    }


def _scalar_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _scalar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_values(child)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        if text:
            yield text


def _assess_claim(sentence, evidence, cited_source_ids, analysis):
    claim_tokens = _tokens(sentence)
    claim_numbers = _numbers(sentence)
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
        row
        for row in ranked
        if row[3]["source_id"] in cited_source_ids and row[1] >= 2 and row[0] >= 0.25 and row[2]
    ]
    conflicts = _jurisdiction_conflicts(sentence, analysis, evidence)
    claim_hash = hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]
    return {
        "claim_id": claim_hash,
        "claim": sentence,
        "supported": supported and numeric_consistent and not conflicts,
        "support_score": round(best[0], 4),
        "best_evidence_type": best[3]["evidence_type"] if best[3] else None,
        "best_evidence_source_id": best[3]["source_id"] if best[3] else None,
        "cited_source_ids": sorted(cited_source_ids),
        "cited_source_supported": bool(cited_matches),
        "numbers": sorted(claim_numbers),
        "numeric_consistent": numeric_consistent,
        "jurisdiction_conflicts": conflicts,
    }


def _cited_source_ids(sentence, evidence):
    lowered = sentence.lower()
    cited = set()
    for item in evidence:
        source_id = item["source_id"]
        if not source_id:
            continue
        values = [source_id, item["title"], item["agency"]]
        acronym = "".join(
            word[0].upper()
            for word in re.findall(r"[A-Za-z]+", item["agency"] or item["title"])
            if word.lower() not in {"and", "of", "the"}
        )
        exact = any(value and value.lower() in lowered for value in values)
        acronym_match = len(acronym) >= 3 and re.search(
            rf"(?<![A-Za-z0-9]){re.escape(acronym)}(?![A-Za-z0-9])", sentence, re.IGNORECASE
        )
        if exact or acronym_match:
            cited.add(source_id)
    return cited


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
        "Every flagged or passing claim still requires human review against the cited current official page.",
    ]
