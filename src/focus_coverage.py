import re

from src.agents.planner_agent import PlannerAgent
from src.agents.profile_agent import ProfileAgent
from src.source_attribution import (
    normalise_markdown_heading,
    normalise_policy_lint_text,
    plain_markdown_claim_text,
    strip_known_attribution_labels,
    visible_markdown_text,
)

FOCUS_COVERAGE_CHECK_NAME = "Selected focus-area coverage"
SCENARIO_COVERAGE_CHECK_NAME = "Selected scenario coverage"


def canonical_coverage_declarations(analysis):
    """Build copy-ready coverage lines only from canonical deterministic IDs."""

    analysis = analysis if isinstance(analysis, dict) else {}
    declarations = []
    profile = analysis.get("profile") if isinstance(analysis.get("profile"), dict) else {}
    candidate = profile.get("scenario_concept")
    if isinstance(candidate, dict):
        concept = next(
            (item for item in ProfileAgent._SCENARIO_CONCEPTS.values() if item["id"] == candidate.get("id")),
            None,
        )
        if concept is not None:
            declarations.append(f"This draft covers the application-recognised {concept['match_terms'][0]} scenario.")

    plan = analysis.get("plan") if isinstance(analysis.get("plan"), dict) else {}
    candidates = plan.get("focus_area_concepts")
    seen = set()
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            concept = PlannerAgent.canonical_focus_concept(candidate.get("id"))
            if concept is None or concept["id"] in seen:
                continue
            seen.add(concept["id"])
            declarations.append(f"This draft includes {concept['match_terms'][0]} in its preparedness planning.")
    return declarations


def _contains_term(text, term):
    words = re.findall(r"[a-z0-9]+", normalise_policy_lint_text(term).casefold())
    if not words:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s\-/]+".join(re.escape(word) for word in words)
    pattern += r"(?:s|es)?(?![a-z0-9])"
    return any(not _is_negated_focus_match(text, match) for match in re.finditer(pattern, text))


def _is_negated_focus_match(text, match):
    sentence_start = max(text.rfind(delimiter, 0, match.start()) for delimiter in ".!?;；\n") + 1
    sentence_ends = [position for delimiter in ".!?;；\n" if (position := text.find(delimiter, match.end())) >= 0]
    sentence_end = min(sentence_ends, default=len(text))
    before = text[sentence_start : match.start()]
    after = text[match.end() : sentence_end]
    negated_command = re.search(
        r"\b(?:(?:do|does|did|will|would|should|must|can|could)\s+)?(?:not|never)\s+"
        r"(?:(?:currently|explicitly|intentionally|adequately|fully|meaningfully)\s+){0,2}"
        r"(?:address(?:es|ed)?|cover(?:s|ed)?|include(?:s|d)?|provide(?:s|d)?|plan(?:s|ned)?|"
        r"consider(?:s|ed)?|discuss(?:es|ed)?|mention(?:s|ed)?)\s+"
        r"(?:(?:a|an|the|all|any|selected|requested|identified|relevant|these|those|this|each|every|both|"
        r"current|specified|application-recognised)\s+){0,4}$",
        before,
    )
    direct_omission = re.search(
        r"\b(?:(?:omit(?:s|ted)?|exclud(?:e|es|ed)|ignor(?:e|es|ed)|skip(?:s|ped)?|lack(?:s|ed)?)\s+|"
        r"(?:leave(?:s)?|left)\s+out\s+)"
        r"(?:(?:a|an|the|all|any|selected|requested|identified|relevant|these|those|this|each|every|both|"
        r"current|specified|application-recognised)\s+){0,4}"
        r"(?:(?:planning|coverage|discussion|provisions?|actions?|attention)\s+"
        r"(?:for|of|about|regarding|relating\s+to)\s+"
        r"(?:(?:a|an|the|any|selected|requested|identified|relevant|these|those|this)\s+){0,4})?$",
        before,
    )
    direct_omission_is_negated = direct_omission is not None and re.search(
        r"\b(?:not|never)(?:\s+(?:intentionally|ever|deliberately|explicitly))?\s*$",
        before[: direct_omission.start()],
    )
    without_term = re.search(
        r"\bwithout\s+(?:(?:a|an|the|all|any|selected|requested|identified|relevant|these|those|this|"
        r"each|every|both|current|specified)\s+){0,4}"
        r"(?:(?:planning|coverage|discussion|provisions?|actions?|attention)\s+"
        r"(?:for|of|about|regarding|relating\s+to)\s+"
        r"(?:(?:a|an|the|any|selected|requested|identified|relevant|these|those|this)\s+){0,4})?$",
        before,
    )
    nothing_planned = re.search(
        r"\bnothing\s+(?:(?:is|was|will\s+be)\s+)?"
        r"(?:planned|provided|included|addressed|covered)\s+for\s+"
        r"(?:(?:a|an|the|any|selected|requested|identified|relevant|these|those|this)\s+){0,4}$",
        before,
    )
    zero_planning = re.search(
        r"\bzero\s+(?:planning|coverage|actions?)\s+(?:(?:is|was)\s+)?(?:provided\s+)?for\s+"
        r"(?:(?:a|an|the|any|selected|requested|identified|relevant|these|those|this)\s+){0,4}$",
        before,
    )
    no_planning_for = re.search(
        r"\b(?:no|neither|zero)\s+(?:plans?|planning|provisions?|coverage|actions?|attention)\s+"
        r"(?:(?:is|was)\s+)?(?:provided\s+)?(?:for|of|about|regarding|relating\s+to)\s+"
        r"(?:(?:a|an|the|any|selected|requested|identified|relevant|these|those|this)\s+){0,4}$",
        before,
    )
    excluded_reference = re.search(
        r"\b(?:unlike|excluding|except(?:\s+for)?|not)\s+(?:(?:a|an|the|any)\s+)?$",
        before,
    )
    comparison_excludes_term = re.search(
        r"\bcompar(?:e|es|ed|ing)\s+(?:(?:a|an|the)\s+)?$",
        before,
    ) and re.search(r"\bbut\s+only\b", after)
    direct_negative_qualifier = re.search(r"\b(?:no|neither|zero)\s*$", before)
    qualifier_is_double_negative = direct_negative_qualifier and re.match(
        r"^\W*(?:(?:is|are|was|were|will|would|should|must|has|have|had|be|been|remain(?:s|ed)?)\W+){0,4}"
        r"(?:(?:not\W+(?:omitted|excluded|ignored|missing|unaddressed|included))|"
        r"(?:left\W+)?(?:unchecked|inaccessible|unavailable|unaddressed|missing|omitted|excluded|ignored))\b",
        after,
    )
    positive_local_predicate = re.search(
        r"\b(?:address(?:es|ed)?|cover(?:s|ed)?|include(?:s|d)?|provide(?:s|d)?|plan(?:s|ned)?|"
        r"consider(?:s|ed)?|discuss(?:es|ed)?|mention(?:s|ed)?|assign(?:s|ed)?|maintain(?:s|ed)?|"
        r"test(?:s|ed)?|prepare(?:s|d)?)\s+"
        r"(?:(?:a|an|the|all|any|selected|requested|identified|relevant|these|those|this|each|every|both|"
        r"current|specified|application-recognised)\s+){0,4}$",
        before,
    )
    explicit_double_negative = bool(
        qualifier_is_double_negative
        or direct_omission_is_negated
        or re.search(
            r"\b(?:not|never)\s+(?:fail|forget)\s+to\s+"
            r"(?:address|cover|include|provide|plan|consider|discuss|mention)\s+"
            r"(?:(?:a|an|the|all|any|selected|requested|identified|relevant|these|those|this)\s+){0,4}$",
            before,
        )
        or (
            re.search(r"\bnever\s+leave\s+$", before)
            and re.match(r"^\W*(?:unchecked|unaddressed|unprepared|inaccessible)\b", after)
        )
        or re.match(
            r"^\W*(?:(?:is|are|was|were|will|would|should|must|has|have|had|be|been|remain(?:s|ed)?)\W+){0,4}"
            r"not\W+(?:optional|omitted|excluded|ignored|missing|unaddressed|inaccessible|unavailable)\b",
            after,
        )
        or re.match(
            r"^\W*(?:cannot|can\W+not|must\W+not)\W+(?:be\W+)?"
            r"(?:omitted|excluded|ignored|missed|left\W+out)\b",
            after,
        )
    )
    clause_text = f"{before}{match.group(0)}{after}"
    broad_exclusion_cue = re.search(
        r"\b(?:not|no|never|omit(?:s|ted)?|exclud(?:e|es|ed)|ignor(?:e|es|ed)|skip(?:s|ped)?|"
        r"lack(?:s|ed)?|unlike|insufficient|irrelevant|inapplicable|unrelated|"
        r"reject(?:s|ed|ing)?|avoid(?:s|ed|ing)?|declin(?:e|es|ed|ing)|refus(?:e|es|ed|ing)|cannot)\b|"
        r"\bunable\s+to\b|\bwithout\b(?!\s+delay\b)|"
        r"\brather\s+than\b|\bout\s+of\s+(?:the\s+)?scope\b|\bdoes\s+not\s+apply\b|"
        r"\bnot\s+relevant\b|\boutside\b[^.!?;；\n]{0,80}\bremit\b",
        clause_text,
    )
    no_term_coverage = re.search(r"\bno\s*$", before) and re.match(
        r"^\W*(?:plans?|actions?|coverage|details?|provisions?)\b", after
    )
    negated_after = re.match(
        r"^\W*(?:(?:is|are|was|were|will|would|should|must|has|have|had|be|been|remain(?:s|ed)?)\W+){0,3}"
        r"(?:(?:intentionally|explicitly|currently)\W+)?"
        r"(?:not\W+(?:be\W+)?(?:addressed|covered|included|provided|planned|considered|discussed|"
        r"applicable|(?:a\W+)?part\W+of)|"
        r"omitted|excluded|ignored|unaddressed|unplanned|uncovered|undeveloped|neglected|disregarded|"
        r"overlooked|missing|absent|"
        r"(?:left|leave(?:s)?)\W+out|"
        r"(?:outside|out\W+of)\W+(?:the\W+)?scope|"
        r"receiv(?:e|es|ed)\W+(?:no|zero|neither|insufficient)\W+"
        r"(?:planning|actions?|coverage|attention))\b",
        after,
    )
    return bool(
        negated_command
        or (direct_omission and not direct_omission_is_negated)
        or without_term
        or nothing_planned
        or zero_planning
        or no_planning_for
        or (direct_negative_qualifier and not qualifier_is_double_negative)
        or no_term_coverage
        or negated_after
        or excluded_reference
        or comparison_excludes_term
        or (
            broad_exclusion_cue
            and not explicit_double_negative
            and not (positive_local_predicate and not negated_command)
        )
    )


def _markdown_container_content(line):
    """Return container content for conservative CommonMark code detection."""

    content = line
    while match := re.match(r"^ {0,3}>[ \t]?", content):
        content = content[match.end() :]
    list_item = re.match(r"^ {0,3}(?:[-+*]|\d+[.)])[ \t]+(?P<content>.*)$", content)
    return list_item.group("content") if list_item else content


def _substantive_visible_text(narrative):
    """Exclude headings and fenced examples so labels alone cannot satisfy coverage."""

    lines = []
    fence = None
    source_section_level = None
    source_section_heading = normalise_markdown_heading("5. Data Sources and Limitations")
    for line in visible_markdown_text(narrative).splitlines():
        container_content = _markdown_container_content(line)
        if fence is not None:
            marker_character, marker_length = fence
            closing_fence = re.match(
                rf"^ {{0,3}}{re.escape(marker_character)}{{{marker_length},}}\s*$",
                container_content,
            )
            if closing_fence:
                fence = None
            continue
        opening_fence = re.match(r"^ {0,3}(?P<marker>`{3,}|~{3,})[^\r\n]*$", container_content)
        if opening_fence:
            marker = opening_fence.group("marker")
            fence = (marker[0], len(marker))
            continue
        if re.match(r"^(?: {4}|\t)", container_content):
            continue
        heading = re.match(r"^ {0,3}(?P<marker>#{1,6})\s+(?P<title>.+?)\s*$", container_content)
        if heading:
            level = len(heading.group("marker"))
            if normalise_markdown_heading(heading.group("title")) == source_section_heading:
                source_section_level = level
                continue
            if source_section_level is not None and level <= source_section_level:
                source_section_level = None
            continue
        if source_section_level is not None:
            continue
        lines.append(container_content)
    content = plain_markdown_claim_text("\n".join(lines)).casefold()
    content = content.replace("won't", "will not").replace("can’t", "cannot").replace("can't", "cannot")
    return re.sub(r"n['’]t\b", " not", content)


def _coverage_visible_text(narrative, analysis):
    """Remove deterministic display labels before scanning model-authored claims."""

    data = analysis.get("data") if isinstance(analysis, dict) else None
    knowledge = analysis.get("knowledge") if isinstance(analysis, dict) else None
    cleaned = strip_known_attribution_labels(
        narrative,
        official_sources=(data or {}).get("sources") or [],
        rag_sources=(knowledge or {}).get("retrieved_chunks") or [],
    )
    return _substantive_visible_text(cleaned)


def evaluate_focus_area_coverage(narrative, analysis):
    """Check only application-recognised focus concepts, never raw U0 values."""

    analysis = analysis if isinstance(analysis, dict) else {}
    plan = analysis.get("plan")
    profile = analysis.get("profile")
    if not isinstance(plan, dict):
        if isinstance(profile, dict) and "concerns" in profile:
            plan = {}
        else:
            return None
    if "focus_area_concepts" in plan:
        concepts = plan.get("focus_area_concepts")
        ignored_count = plan.get("ignored_focus_area_count", 0)
    elif isinstance(profile, dict) and "concerns" in profile:
        concerns = profile.get("concerns")
        if not isinstance(concerns, list):
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The legacy focus-area input cannot be migrated safely; regenerate the report.",
            }
        concepts, ignored_count = PlannerAgent._resolve_focus_areas(concerns)
        if ignored_count:
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": (
                    "The legacy focus-area input is not an exact current allowlist match; regenerate the report "
                    "before review or export."
                ),
            }
    else:
        return None
    if not isinstance(concepts, list):
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": "The deterministic focus-area contract is malformed; regenerate the analysis snapshot.",
        }

    visible = _coverage_visible_text(narrative, analysis)
    missing = []
    for candidate in concepts:
        if not isinstance(candidate, dict):
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The deterministic focus-area contract is malformed; regenerate the analysis snapshot.",
            }
        concept = PlannerAgent.canonical_focus_concept(candidate.get("id"))
        if concept is None:
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The deterministic focus-area contract is unknown; regenerate the analysis snapshot.",
            }
        label = concept["label"]
        terms = concept["match_terms"]
        if not any(_contains_term(visible, term) for term in terms):
            missing.append(label)

    if type(ignored_count) is not int or ignored_count < 0:
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": "The deterministic focus-area ignore count is malformed; regenerate the analysis snapshot.",
        }

    if missing:
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": (
                "Cover every application-recognised focus area in the model-authored narrative (missing: "
                + ", ".join(missing)
                + ")."
            ),
        }

    ignored_note = (
        f" {ignored_count} unrecognised U0 focus value(s) were not promoted into trusted planning instructions."
        if ignored_count
        else ""
    )
    return {
        "status": "pass",
        "name": FOCUS_COVERAGE_CHECK_NAME,
        "detail": f"All {len(concepts)} application-recognised focus area(s) are represented.{ignored_note}",
    }


def evaluate_scenario_coverage(narrative, analysis):
    """Require the allowlisted scenario concept in substantive model-authored text."""

    profile = analysis.get("profile") if isinstance(analysis, dict) else None
    if not isinstance(profile, dict):
        return None
    if "scenario_concept" in profile:
        candidate = profile.get("scenario_concept")
    elif "scenario" in profile:
        candidate = ProfileAgent.resolve_scenario_concept(profile.get("scenario"))
        if candidate is None:
            return {
                "status": "fail",
                "name": SCENARIO_COVERAGE_CHECK_NAME,
                "detail": (
                    "The legacy scenario input is not an exact current allowlist match; regenerate the report "
                    "before review or export."
                ),
            }
    else:
        return None
    if candidate is None:
        # Current profiles explicitly record None for unrecognised U0 scenario
        # text. It is neither promoted into a trusted concept nor replayed.
        return None
    if not isinstance(candidate, dict):
        return {
            "status": "fail",
            "name": SCENARIO_COVERAGE_CHECK_NAME,
            "detail": "The deterministic scenario contract is malformed; regenerate the analysis snapshot.",
        }
    concept = next(
        (item for item in ProfileAgent._SCENARIO_CONCEPTS.values() if item["id"] == candidate.get("id")),
        None,
    )
    if concept is None:
        return {
            "status": "fail",
            "name": SCENARIO_COVERAGE_CHECK_NAME,
            "detail": "The deterministic scenario contract is unknown; regenerate the analysis snapshot.",
        }
    visible = _coverage_visible_text(narrative, analysis)
    passed = any(_contains_term(visible, term) for term in concept["match_terms"])
    return {
        "status": "pass" if passed else "fail",
        "name": SCENARIO_COVERAGE_CHECK_NAME,
        "detail": (
            f"The model-authored narrative represents the application-recognised {concept['label']} scenario."
            if passed
            else f"Cover the application-recognised {concept['label']} scenario in substantive narrative content."
        ),
    }
