"""Diagnostic body-claim inventory; lexical alignment is never semantic proof.

Spans refer to the exact input report (Python character offsets). Source excerpts
live only in the separately validated final SDK snapshot. This module neither
changes the governed quality gate nor upgrades U0 or source metadata to evidence.
"""

from __future__ import annotations

import re

from src import source_attribution as attribution
from src.focus_coverage import canonical_coverage_declarations
from src.markdown_tables import is_markdown_table_separator, parse_markdown_table_row
from src.model_evidence import text_sha256, unavailable_model_evidence, validate_model_evidence
from src.report_grounding import _numbers, _tokens
from src.report_template import GOVERNANCE_NOTICE_MARKDOWN

BODY_CLAIM_EVIDENCE_METHOD = "body_claim_evidence_v1"
MAX_BODY_CLAIMS = 2000
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST = re.compile(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)(?:\[[ xX]\]\s+)?")
_USER = re.compile(
    r"^(?:\[U0\]\s*)?(?:the user (?:reports?|states?|provided|describes?|expects?|requests?)\b|"
    r"according to (?:the )?user\b|user[- ](?:reported|provided)\b)",
    re.I,
)
_UNCERTAIN = re.compile(
    r"^(?:unverified (?:proposal|candidate|planning assumption)\b|"
    r"proposed for (?:local|organisational|organizational) review\b|"
    r"to be confirmed(?: by|[.:]|$)|(?:it is |the .{0,60} is )?(?:unknown|unverified) whether\b)",
    re.I,
)
_PROCEDURE = re.compile(
    r"^(?:(?:day|week)\s+\d+\s*:\s*)?(?:(?:the )?(?:responsible |preparedness )?"
    r"(?:lead|coordinator|officer|organisation|organization|team|committee|reviewer)\s+"
    r"(?:will |should |must |is to )?)?"
    r"(?:assign|appoint|nominate|record|document|schedule|maintain|review|update|confirm|verify)\b",
    re.I,
)
_ADMIN_OBJECT = re.compile(
    r"\b(?:owners?|responsibilities|contacts?|contact (?:list|details)|review (?:date|record|checkpoint)|"
    r"checkpoints?|meeting|minutes|version|sign[- ]off|approval record|exercise record|"
    r"action (?:register|log)|preparedness lead)\b",
    re.I,
)
_EXTERNAL_PREDICATE = re.compile(
    r"\b(?:reduces?|prevents?|protects?|ensures?|guarantees?|effective|safe|risk|smoke|"
    r"heat|burns?|shelter|hydration|water|evacuat\w*|fire|first aid|air quality)\b",
    re.I,
)
_NEGATION = re.compile(r"\b(?:not|never|avoid|without|cannot)\b|n't\b", re.I)
_CONDITION = re.compile(r"\b(?:if|unless|only when|provided that|subject to)\b", re.I)


def _catalog(analysis):
    analysis = analysis if isinstance(analysis, dict) else {}
    return {
        "rag": [
            {"source_id": str(item.get("source_id") or ""), "title": str(item.get("title") or "")}
            for item in (analysis.get("knowledge") or {}).get("retrieved_chunks", []) or []
            if isinstance(item, dict)
        ],
        "official": [
            {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
            for item in (analysis.get("data") or {}).get("sources", []) or []
            if isinstance(item, dict)
        ],
    }


def _bindings(catalog):
    result = {}
    for kind, id_key, label_fn, token_fn in (
        ("rag", "source_id", attribution.format_rag_attribution, attribution.format_rag_citation_token),
        ("official", "id", attribution.format_official_attribution, attribution.format_official_citation_token),
    ):
        for source in catalog[kind]:
            if not source.get(id_key) or not source.get("title" if kind == "rag" else "name"):
                continue
            identity = {"source_id": attribution._normalise_source_id(source[id_key]), "source_type": kind}
            for value in (label_fn(source), token_fn(source)):
                if value in result and result[value] != identity:
                    raise ValueError("Ambiguous body-claim citation identity.")
                result[value] = identity
    return result


def _blank(text):
    return re.sub(r"[^\r\n]", " ", text)


def _visible_mask(report):
    """Use the existing visibility rules without discarding original offsets."""
    masked = report
    for pattern in (attribution._HTML_COMMENT, attribution._UNCLOSED_HTML_COMMENT):
        masked = pattern.sub(lambda match: _blank(match[0]), masked)
    previous = None
    while previous != masked:
        previous = masked
        for pattern in (
            attribution._NON_VISIBLE_HTML_BLOCK,
            attribution._HIDDEN_HTML_BLOCK,
            attribution._UNCLOSED_NON_VISIBLE_HTML_BLOCK,
            attribution._UNCLOSED_HIDDEN_HTML_BLOCK,
        ):
            masked = pattern.sub(lambda match: _blank(match[0]), masked)
    notice = GOVERNANCE_NOTICE_MARKDOWN.strip()
    masked = masked.replace(notice, _blank(notice))
    return masked


def _classification_scope(analysis):
    """Store canonical IDs, never user prose, for exact offline scope replay."""
    analysis = analysis if isinstance(analysis, dict) else {}
    profile = analysis.get("profile") or {}
    scenario = profile.get("scenario_concept") if isinstance(profile, dict) else None
    scenario_id = scenario.get("id") if isinstance(scenario, dict) else None
    if not canonical_coverage_declarations({"profile": {"scenario_concept": {"id": scenario_id}}}):
        scenario_id = None
    plan = analysis.get("plan") or {}
    candidates = plan.get("focus_area_concepts") if isinstance(plan, dict) else None
    focus_ids = []
    for candidate in candidates if isinstance(candidates, list) else []:
        value = candidate.get("id") if isinstance(candidate, dict) else None
        if value not in focus_ids and canonical_coverage_declarations(
            {"plan": {"focus_area_concepts": [{"id": value}]}}
        ):
            focus_ids.append(value)
    return {"version": 2, "scenario_id": scenario_id, "focus_ids": focus_ids}


def _scope_analysis(scope):
    return {
        "profile": {"scenario_concept": {"id": scope["scenario_id"]}},
        "plan": {"focus_area_concepts": [{"id": value} for value in scope["focus_ids"]]},
    }


def _classify(text, declarations=()):
    if text in declarations:
        return "organisational_procedure", False
    if _USER.search(text):
        return "user_context", False
    if _UNCERTAIN.search(text):
        return "uncertain", False
    if _PROCEDURE.search(text) and _ADMIN_OBJECT.search(text) and not _EXTERNAL_PREDICATE.search(text):
        return "organisational_procedure", False
    return "external_assertion", True


def _sentence_spans(text, bindings):
    # Protect complete display labels, including punctuation in source titles.
    protected = text
    if bindings:
        matcher = re.compile("|".join(re.escape(item) for item in sorted(bindings, key=len, reverse=True)))
        protected = matcher.sub(lambda match: "C" * len(match[0]), protected)
    else:
        matcher = None
    start, index = 0, 0
    while index < len(protected):
        char = protected[index]
        if char not in ".!?" or (index + 1 < len(text) and not text[index + 1].isspace()):
            index += 1
            continue
        # Decimal points and common abbreviation stops are not sentence ends.
        if char == "." and re.search(r"\b(?:e\.g|i\.e|Mr|Mrs|Dr|St|vs)\.$", text[: index + 1], re.I):
            index += 1
            continue
        end = index + 1
        cursor = end
        # Citation(s) immediately following a full stop belong to that sentence.
        while matcher is not None:
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            citation = matcher.match(text, cursor)
            if citation is None:
                break
            end = cursor = citation.end()
            if cursor < len(text) and text[cursor] in ".!?":
                end = cursor = cursor + 1
        yield start, end
        start = end
        index = max(end, index + 1)
    if start < len(text):
        yield start, len(text)


def _block_claims(report, masked, start, end, block_type, section, bindings, row, column, declarations):
    source = masked[start:end]
    for relative_start, relative_end in _sentence_spans(source, bindings):
        while relative_start < relative_end and source[relative_start].isspace():
            relative_start += 1
        while relative_end > relative_start and source[relative_end - 1].isspace():
            relative_end -= 1
        a, b = start + relative_start, start + relative_end
        visible = source[relative_start:relative_end]
        citations = {}
        for label in sorted(bindings, key=len, reverse=True):
            if label in visible:
                identity = bindings[label]
                citations[(identity["source_type"], identity["source_id"])] = identity
                visible = visible.replace(label, " ")
        body = attribution.plain_markdown_claim_text(visible).strip()
        words = _WORD.findall(body)
        # Short assertions and imperatives remain visible to review. A verb
        # allowlist would silently discard valid recommendations (e.g. Hydrate).
        if len(words) < 2 and not (words and _numbers(body)):
            continue
        classification, required = _classify(body, declarations)
        claim = report[a:b]
        yield {
            "claim_id": text_sha256(f"{a}:{b}:{claim}")[:24],
            "claim": claim,
            "section": section,
            "block_type": block_type,
            "span": {"start": a, "end": b},
            "table_row": row,
            "table_column": column,
            "classification": classification,
            "citation_required": required,
            "cited_source_ids": sorted({item["source_id"] for item in citations.values()}),
            "citations": [citations[key] for key in sorted(citations)],
        }


def extract_body_claims(report_text, analysis) -> list[dict]:
    """Inventory substantive prose, list items and independent table cells.

    Complete raw text is retained, including claims longer than 600 characters.
    Repeated wording at different positions receives different stable IDs.
    """
    return _extract_body_claims(report_text, analysis, canonical_coverage_declarations(analysis))


def _extract_body_claims(report_text, analysis, declarations):
    report = str(report_text or "")
    catalog = _catalog(analysis)
    bindings = _bindings(catalog)
    masked = _visible_mask(report)
    lines = masked.splitlines(keepends=True)
    result = []
    offset, section, appendix_level, fence, table_row = 0, "", None, None, 0
    paragraph_start, paragraph_end = None, None
    list_content_indent = None
    table_context = False

    def emit(start, end, block_type, row=None, column=None):
        result.extend(
            _block_claims(report, masked, start, end, block_type, section, bindings, row, column, declarations)
        )

    def flush():
        nonlocal paragraph_start, paragraph_end
        if paragraph_start is not None:
            emit(paragraph_start, paragraph_end, "prose")
        paragraph_start = paragraph_end = None

    for line_index, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        heading = _HEADING.match(line)
        bullet = _LIST.match(line)
        next_line = lines[line_index + 1].strip() if line_index + 1 < len(lines) else ""
        table_bounds = _body_table_bounds(line, next_line, table_context)
        leading_spaces = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
        indented_code = leading_spaces >= 4 and (
            list_content_indent is None or leading_spaces >= list_content_indent + 4
        )
        fence_line = line.expandtabs(4)
        if list_content_indent is not None and leading_spaces >= list_content_indent:
            fence_line = fence_line[list_content_indent:]
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", fence_line)
        if fence or fence_match:
            flush()
            if fence:
                if fence_match and fence_match[1][0] == fence[0] and len(fence_match[1]) >= len(fence):
                    fence = None
            else:
                fence = fence_match[1]
            offset += len(raw)
            continue
        if heading:
            flush()
            title = heading[2].strip()
            if appendix_level is not None and len(heading[1]) <= appendix_level:
                appendix_level = None
            if title in {"Evidence Tables", "Human Review Sign-off"}:
                appendix_level = len(heading[1])
            section = title
            table_row = 0
            list_content_indent = None
            table_context = False
        elif appendix_level is not None or not stripped or indented_code:
            flush()
            table_row = 0
            table_context = False
        elif (
            attribution._REFERENCE_DEFINITION.match(line)
            or not attribution.strip_application_source_bindings(
                line, rag_sources=catalog["rag"], official_sources=catalog["official"]
            ).strip()
        ):
            flush()
        elif table_bounds is not None:
            flush()
            list_content_indent = None
            table_context = True
            if not _body_table_separator(line) and not _body_table_separator(next_line):
                table_row += 1
                for column, (left, right) in enumerate(table_bounds, 1):
                    emit(offset + left, offset + right, "table_cell", table_row, column)
        else:
            table_row = 0
            table_context = False
            if bullet:
                flush()
                list_content_indent = re.match(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)", line.expandtabs(4)).end()
                kind = "checklist" if re.search(r"\[[ xX]\]", bullet[0]) else "bullet"
                emit(offset + bullet.end(), offset + len(line), kind)
            else:
                list_content_indent = list_content_indent if leading_spaces else None
                if paragraph_start is None:
                    paragraph_start = offset
                paragraph_end = offset + len(line)
        offset += len(raw)
    flush()
    return result


def _body_table_separator(line):
    # Virtual edges are local to this new diagnostic. Historical shared parser
    # and grounding contracts still require outer pipes exactly as before.
    return is_markdown_table_separator("|" + line.strip().strip("|") + "|")


def _body_table_bounds(line, next_line, table_context):
    pipes = [
        index
        for index, char in enumerate(line)
        if char == "|" and (len(line[:index]) - len(line[:index].rstrip("\\"))) % 2 == 0
    ]
    if not pipes:
        return None
    if parse_markdown_table_row(line) is None and not (table_context or _body_table_separator(next_line)):
        return None
    left, right = len(line) - len(line.lstrip()), len(line.rstrip())
    boundaries = [left - 1, *pipes, right]
    if pipes[0] == left:
        boundaries.pop(0)
    if pipes[-1] == right - 1:
        boundaries.pop()
    return [(a + 1, b) for a, b in zip(boundaries, boundaries[1:])]


def _body_text(claim, bindings):
    value = _visible_mask(claim)
    for label in sorted(bindings, key=len, reverse=True):
        value = value.replace(label, " ")
    return attribution.plain_markdown_claim_text(value)


def _cross_statement_numeric_context(tokens, numbers, text):
    """Flag lexical evidence assembled across different uses of one value.

    This is a review heuristic, not a population or predicate parser. Requiring
    two missing context words tolerates one carried context word (for example,
    a survey description), but can miss sparse or paraphrased substitutions.
    """
    if not numbers:
        return False
    statements = [
        (_tokens(part), _numbers(part))
        for start, end in _sentence_spans(text, {})
        for part in text[start:end].split(";")
        if part.strip()
    ]
    for number in numbers:
        contexts = [words for words, values in statements if number in values]
        if len(contexts) < 2:
            continue
        aligned = tokens & set().union(*contexts)
        if all(len(aligned - words) >= 2 for words in contexts):
            return True
    return False


def _source_check(body, identity, visible, snapshot_status):
    passages = [
        (index, item)
        for index, item in enumerate(visible)
        if identity["source_type"] == "rag"
        and attribution._normalise_source_id(item.get("source_id")) == identity["source_id"]
    ]
    reasons, refs, candidates = [], [], []
    if identity["source_type"] != "rag":
        reasons.append("official_metadata_is_not_submitted_passage_evidence")
    elif snapshot_status != "captured":
        reasons.append("final_submitted_passages_unavailable")
    elif not passages:
        reasons.append("cited_source_not_submitted")
    tokens, numbers = _tokens(body), _numbers(body)
    for index, item in passages:
        text = item["text"]
        overlap = len(tokens & _tokens(text))
        score = overlap / max(1, len(tokens))
        flags = []
        if not numbers.issubset(_numbers(text)):
            flags.append("numeric_context_mismatch")
        if _cross_statement_numeric_context(tokens, numbers, text):
            flags.append("possible_cross_statement_numeric_context")
        if bool(_NEGATION.search(body)) != bool(_NEGATION.search(text)):
            flags.append("possible_negation_mismatch")
        if _CONDITION.search(text) and not _CONDITION.search(body):
            flags.append("possible_omitted_condition")
        matched = overlap >= 2 and score >= 0.3 and not flags
        candidates.append((matched, score, flags))
        refs.append(
            {
                "passage_index": index,
                "source_id": item.get("source_id"),
                "chunk_id": item.get("chunk_id"),
                "visible_text_sha256": text_sha256(text),
            }
        )
    if candidates:
        best = max(candidates, key=lambda item: (item[0], item[1]))
        status = "lexical_match" if best[0] else "no_lexical_match"
        reasons.extend(best[2])
        if not best[0]:
            reasons.append("no_sufficient_lexical_match_in_cited_passages")
        score = round(best[1], 4)
    else:
        status = "no_lexical_match" if snapshot_status == "captured" and identity["source_type"] == "rag" else "unknown"
        score = None
    return {
        **identity,
        "visible_passage_present": bool(passages),
        "support_status": status,
        "support_score": score,
        "reasons": reasons,
        "passage_refs": refs,
    }


def _evaluate(report_text, analysis, visible, snapshot_status, *, classification_scope=None):
    catalog = _catalog(analysis)
    bindings = _bindings(catalog)
    # Absence is the archived v1 classification contract, not today's classifier.
    declarations = (
        canonical_coverage_declarations(_scope_analysis(classification_scope)) if classification_scope else ()
    )
    extracted = _extract_body_claims(report_text, analysis, declarations)
    claims = []
    for original in extracted[:MAX_BODY_CLAIMS]:
        claim = dict(original)
        required, citations = claim["citation_required"], claim["citations"]
        claim["citation_status"] = "cited" if citations else "missing" if required else "not_required"
        checks = [
            _source_check(_body_text(claim["claim"], bindings), identity, visible, snapshot_status)
            for identity in citations
        ]
        reasons = ["missing_body_citation"] if claim["citation_status"] == "missing" else []
        if checks:
            statuses = {item["support_status"] for item in checks}
            support = (
                "no_lexical_match"
                if "no_lexical_match" in statuses
                else "unknown"
                if "unknown" in statuses
                else "lexical_match"
            )
            reasons.extend(reason for check in checks for reason in check["reasons"])
        elif required:
            support = "unknown"
            reasons.append("no_cited_passage_to_check")
        else:
            support = "not_applicable"
        claim.update(support_status=support, reasons=sorted(set(reasons)), source_checks=checks)
        claims.append(claim)
    count = len(claims)
    required = sum(item["citation_required"] for item in claims)
    cited_required = sum(item["citation_required"] and item["citation_status"] == "cited" for item in claims)
    review = sum(bool(item["reasons"]) for item in claims)
    return {
        "method": BODY_CLAIM_EVIDENCE_METHOD,
        **({"classification_scope": classification_scope} if classification_scope is not None else {}),
        "scope": "final_sdk_submitted_rag_passages_only",
        "snapshot_status": snapshot_status,
        "status": "review_required" if review or len(extracted) > count else "clear" if count else "not_applicable",
        "source_catalog": catalog,
        "metrics": {
            "claims_evaluated": count,
            "claims_requiring_citation": required,
            "cited_claims": sum(item["citation_status"] == "cited" for item in claims),
            "missing_citations": sum(item["citation_status"] == "missing" for item in claims),
            "lexical_match_claims": sum(item["support_status"] == "lexical_match" for item in claims),
            "no_lexical_match_claims": sum(item["support_status"] == "no_lexical_match" for item in claims),
            "unknown_support_claims": sum(item["support_status"] == "unknown" for item in claims),
            "review_required_claims": review,
            "citation_coverage_rate": round(cited_required / required, 4) if required else None,
        },
        "processing": {
            "complete": count == len(extracted),
            "claims_extracted": len(extracted),
            "claims_evaluated": count,
            "claims_omitted": len(extracted) - count,
            "max_claims": MAX_BODY_CLAIMS,
        },
        "claims": claims,
        "limitations": [
            "Diagnostic only; this result never changes the governed approval gate.",
            "Lexical matches are not proof of entailment, truth, currency, provider receipt or model attention.",
            "Only validated passages in the final SDK request are checked; U0, prior drafts and metadata are not support.",
            "Claim classification, sentence boundaries, negation and condition flags are conservative heuristics requiring human review.",
            "Repeated-value context checks can miss sparse or paraphrased substitutions and can flag valid multi-statement summaries.",
            "Citations stay within a sentence or table cell; prose is retained in full and processing omissions are reported explicitly.",
        ],
    }


def evaluate_body_claim_evidence(report_text, analysis, snapshot=None) -> dict:
    """Keep citation coverage observable even when final SDK evidence is absent."""
    snapshot = unavailable_model_evidence() if snapshot is None else snapshot
    try:
        visible = validate_model_evidence(snapshot, analysis, report_text=str(report_text or ""))
        status = snapshot["status"]
    except (ValueError, TypeError, KeyError, AttributeError):
        visible, status = [], "invalid_snapshot"
    return _evaluate(report_text, analysis, visible, status, classification_scope=_classification_scope(analysis))


def validate_body_claim_evidence(evaluation, report_text, snapshot=None, *, analysis=None):
    """Strictly recompute the new sibling; historical diagnostics remain separate.

    Export creation passes the full frozen analysis. Offline packages retain only
    an audited metadata catalogue and SDK excerpts, so raw-source revalidation is
    unavailable there; snapshot framing, claim positions and every check are still
    recomputed. No unknown field is exempted from the package leakage scanner.
    """
    snapshot = unavailable_model_evidence() if snapshot is None else snapshot
    if not isinstance(evaluation, dict):
        raise ValueError("Malformed body-claim diagnostic.")
    scope = evaluation.get("classification_scope")
    if "classification_scope" in evaluation:
        if (
            not isinstance(scope, dict)
            or set(scope) != {"version", "scenario_id", "focus_ids"}
            or type(scope["version"]) is not int
            or scope["version"] != 2
            or not (scope["scenario_id"] is None or isinstance(scope["scenario_id"], str))
            or not isinstance(scope["focus_ids"], list)
            or len(scope["focus_ids"]) > 256
            or any(not isinstance(value, str) for value in scope["focus_ids"])
            or scope != _classification_scope(_scope_analysis(scope))
        ):
            raise ValueError("Malformed body-claim classification scope.")
    if analysis is not None:
        visible = validate_model_evidence(snapshot, analysis, report_text=report_text)
        if scope is not None and scope != _classification_scope(analysis):
            raise ValueError("Body-claim classification scope differs from the frozen analysis.")
        expected = _evaluate(report_text, analysis, visible, snapshot["status"], classification_scope=scope)
    else:
        if not isinstance(evaluation, dict):
            raise ValueError("Malformed body-claim diagnostic.")
        catalog = evaluation.get("source_catalog")
        if not isinstance(catalog, dict) or set(catalog) != {"rag", "official"}:
            raise ValueError("Malformed body-claim source catalogue.")
        for key, fields in (("rag", {"source_id", "title"}), ("official", {"id", "name"})):
            if (
                not isinstance(catalog[key], list)
                or len(catalog[key]) > 256
                or any(
                    not isinstance(item, dict)
                    or set(item) != fields
                    or any(not isinstance(value, str) or len(value) > 2000 for value in item.values())
                    for item in catalog[key]
                )
            ):
                raise ValueError("Malformed body-claim source catalogue entries.")
        visible = validate_model_evidence(snapshot, report_text=report_text)
        minimal = {"knowledge": {"retrieved_chunks": catalog["rag"]}, "data": {"sources": catalog["official"]}}
        expected = _evaluate(report_text, minimal, visible, snapshot["status"], classification_scope=scope)
    if evaluation != expected:
        raise ValueError("Body-claim diagnostic differs from its bound report and submitted evidence.")
    return evaluation
