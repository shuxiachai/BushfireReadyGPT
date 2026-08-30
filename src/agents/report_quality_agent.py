import hashlib
import re
from collections import defaultdict

from src.report_template import REPORT_TEMPLATE_SECTIONS, extract_narrative_body
from src.safety_boundary import evaluate_safety_boundaries
from src.source_attribution import (
    canonical_official_labels,
    canonical_official_source_ids_on_plain_lines,
    extract_markdown_section,
    has_model_authored_raw_html,
    has_model_authored_url,
    has_unbound_attribution_marker,
    normalise_markdown_heading,
    plain_markdown_claim_text,
    strip_application_source_bindings,
    strip_known_attribution_labels,
    visible_markdown_text,
)


class ReportQualityAgent:
    """Checks generated reports against the project quality requirements."""

    REQUIRED_SECTION_HEADINGS = [
        title.partition(". ")[2]
        for title, _instruction in REPORT_TEMPLATE_SECTIONS
        if title.partition(". ")[2] != "Title"
    ]

    LEGACY_OFFICIAL_SOURCE_TERMS = [
        "Bureau of Meteorology",
        "BoM",
        "000",
        "fire service",
        "emergency services",
        "local council",
        "official",
        "state emergency",
    ]

    CANDIDATE_PLACE_TERMS = [
        "lecture hall",
        "gymnasium",
        "library",
        "sports field",
        "carpark",
        "administration building",
    ]
    UNSAFE_CONFIRMATION_TERMS = ["confirmed safe", "confirmed assembly point", "guaranteed safe"]
    STOPWORDS = {
        "and",
        "are",
        "for",
        "from",
        "has",
        "have",
        "into",
        "must",
        "not",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "their",
        "this",
        "to",
        "with",
    }

    def run(self, report_text, *, official_sources=None, rag_sources=None):
        text = report_text or ""
        narrative = extract_narrative_body(text)
        scored_narrative = strip_application_source_bindings(
            narrative,
            official_sources=official_sources or [],
            rag_sources=rag_sources or [],
        )
        claim_narrative = strip_known_attribution_labels(
            scored_narrative,
            official_sources=official_sources or [],
            rag_sources=rag_sources or [],
        )
        lint_narrative = plain_markdown_claim_text(claim_narrative)
        checks = [
            self._check_substantive_narrative(claim_narrative),
            self._check_sections(claim_narrative),
            self._check_official_sources(narrative, official_sources),
            self._check_safety_disclaimer(text),
            self._check_emergency_number(text),
            self._check_action_plan(claim_narrative),
            self._check_checklist(claim_narrative),
            self._check_role_assignment(claim_narrative),
            self._check_candidate_assembly_language(lint_narrative),
            self._check_safety_boundaries(lint_narrative),
            self._check_model_authored_urls(claim_narrative),
            self._check_model_authored_raw_html(claim_narrative),
            self._check_unbound_attribution_markers(
                claim_narrative,
                enforce=official_sources is not None or rag_sources is not None,
            ),
            self._check_evidence_tables(text),
            self._check_evidence_confidence(text),
            self._check_human_review_status(text),
        ]

        passed = sum(1 for item in checks if item["status"] == "pass")
        warnings = sum(1 for item in checks if item["status"] == "warning")
        failed = sum(1 for item in checks if item["status"] == "fail")
        blocking_failures = [
            {"name": item["name"], "detail": item["detail"]} for item in checks if item["status"] == "fail"
        ]

        return {
            "checks": checks,
            "summary": {
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
                "total": len(checks),
            },
            "approval_gate": {
                "passed": not blocking_failures,
                "status": "passed" if not blocking_failures else "blocked",
                "blocking_failures": blocking_failures,
            },
            "assessment_scope": (
                "Deterministic structure and English-language safety-boundary lint only. "
                "Passing checks do not verify factual accuracy, "
                "official currency, legal validity or operational safety."
            ),
        }

    def _check_substantive_narrative(self, text):
        headings = re.findall(r"(?m)^ {0,3}#{1,6}\s+\S.*$", text)
        content_lines = [
            line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "|", "- [ ]", "- [x]", "- [X]"))
        ]
        words = [word.lower() for word in re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", "\n".join(content_lines))]
        content_words = [word for word in words if word not in self.STOPWORDS and len(word) > 2]
        unique_content_words = set(content_words)
        max_word_frequency = max(
            (content_words.count(word) for word in unique_content_words),
            default=0,
        )
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", "\n".join(content_lines)))
        normalised_lines = {re.sub(r"\s+", " ", line.strip().lower()) for line in content_lines}
        line_diversity = len(normalised_lines) / max(len(content_lines), 1)
        is_diverse = (
            len(unique_content_words) >= 55
            and max_word_frequency <= max(12, int(len(content_words) * 0.12))
            and sentence_count >= 10
            and line_diversity >= 0.55
        )
        if len(words) >= 250 and len(headings) >= 10 and len(content_lines) >= 10 and is_diverse:
            return self._result(
                "pass",
                "Substantive narrative",
                "The model-authored body contains substantial prose and multi-section structure.",
            )
        return self._result(
            "fail",
            "Substantive narrative",
            (
                "The model-authored body is too short or insufficiently structured "
                f"({len(words)} prose words, {len(unique_content_words)} distinct content words, "
                f"{sentence_count} sentences, {len(headings)} headings, "
                f"{len(content_lines)} content lines)."
            ),
        )

    def _check_sections(self, text):
        sections = self._extract_sections(text)
        heading_counts = self._required_heading_counts(text)
        missing = [section for section in self.REQUIRED_SECTION_HEADINGS if heading_counts[section.lower()] == 0]
        duplicated = [section for section in self.REQUIRED_SECTION_HEADINGS if heading_counts[section.lower()] > 1]
        shallow = []
        for section in self.REQUIRED_SECTION_HEADINGS:
            if section.lower() not in sections or "checklist" in section.lower():
                continue
            words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", sections[section.lower()])
            unique = {word.lower() for word in words if word.lower() not in self.STOPWORDS and len(word) > 2}
            if len(words) < 7 or len(unique) < 4:
                shallow.append(section)
        if not missing and not duplicated and not shallow:
            return self._result(
                "pass",
                "Required sections",
                "Every required heading contains section-specific substantive content.",
            )
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if duplicated:
            detail.append("duplicated: " + ", ".join(duplicated))
        if shallow:
            detail.append("insufficient content: " + ", ".join(shallow))
        return self._result(
            "fail", "Required sections", "Required structure is incomplete (" + "; ".join(detail) + ")."
        )

    def _check_official_sources(self, text, official_sources=None):
        if official_sources is None:
            found = [term for term in self.LEGACY_OFFICIAL_SOURCE_TERMS if term.lower() in text.lower()]
            if len(found) >= 4:
                return self._result(
                    "pass", "Official sources", "The report includes multiple official information sources."
                )
            return self._result(
                "fail",
                "Official sources",
                "Add the state fire service, local council, Bureau of Meteorology and 000 where relevant.",
            )

        labels = canonical_official_labels(official_sources)
        if has_model_authored_raw_html(text):
            return self._result(
                "fail",
                "Official sources",
                "Use visible plain-text or Markdown list citation lines; raw HTML is not accepted.",
            )
        section = extract_markdown_section(visible_markdown_text(text), "Data Sources and Limitations")
        attributed_ids = canonical_official_source_ids_on_plain_lines(section, official_sources)
        if len(labels) >= 2 and len(attributed_ids) >= 2:
            return self._result(
                "pass",
                "Official sources",
                "The source section attributes at least two registered official information sources.",
            )
        return self._result(
            "fail",
            "Official sources",
            (
                "Keep one real visible Markdown Data Sources and Limitations section. The application must bind "
                "at least two complete registered official sources there as plain-text or Markdown bullet lines; "
                "raw HTML, hidden markup and incomplete source records are not accepted."
            ),
        )

    def _check_safety_disclaimer(self, text):
        lowered = text.lower()
        keywords = ["safety disclaimer", "official", "live", "evacuation order"]
        if all(keyword in lowered for keyword in keywords):
            return self._result(
                "pass",
                "Safety disclaimer",
                "The report includes a safety disclaimer and official verification reminder.",
            )
        return self._result(
            "fail",
            "Safety disclaimer",
            "The report should clearly state that live warnings and evacuation orders must come from official sources.",
        )

    def _check_emergency_number(self, text):
        if "000" in text:
            return self._result("pass", "Emergency number 000", "The report includes 000.")
        return self._result("fail", "Emergency number 000", "The report does not mention 000.")

    def _check_action_plan(self, text):
        action_plan = self._extract_sections(text).get("action plan", "")
        immediate_patterns = (
            r"\bdays?\s*(?:1|one)\b",
            r"\bfirst\s+day\b",
            r"\btoday\b",
            r"\bimmediate(?:ly)?\b",
            r"\bwithin\s+(?:the\s+)?(?:first\s+)?24\s*(?:hours?|hrs?)\b",
            r"\b(?:0|zero)\s*(?:-|\u2013|\u2014|to)\s*24\s*(?:hours?|hrs?)\b",
            r"(?m)^\s*(?:\|\s*)?1\s*(?:\||[.)])",
        )
        if action_plan and any(re.search(pattern, action_plan, flags=re.IGNORECASE) for pattern in immediate_patterns):
            return self._result("pass", "Action plan", "The report includes an immediate, time-based action plan.")
        return self._result(
            "fail",
            "Action plan",
            "The report should include a Day 1, today or first-24-hours action item.",
        )

    def _check_checklist(self, text):
        lowered = text.lower()
        has_markdown_checkbox = "- [ ]" in text or "- [x]" in lowered
        if "checklist" in lowered and has_markdown_checkbox:
            return self._result("pass", "Checklist", "The report includes a checkable checklist.")
        return self._result("fail", "Checklist", "Use Markdown checkboxes for the checklist.")

    def _check_role_assignment(self, text):
        role_terms = [
            "roles",
            "responsib",
            "organisation",
            "management",
            "coordinator",
            "warden",
            "staff",
            "first aid",
            "communication",
            "backup",
        ]
        found = [term for term in role_terms if term in text.lower()]
        if len(found) >= 4:
            return self._result("pass", "Roles and responsibilities", "The report covers key role responsibilities.")
        return self._result(
            "fail",
            "Roles and responsibilities",
            (
                "Add audience-appropriate roles for the responsible organisation, operational lead, "
                "communications, first aid and backup coverage."
            ),
        )

    def _check_candidate_assembly_language(self, text):
        lowered = text.lower()
        unsafe_sentence = None
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", lowered):
            if not any(term in sentence for term in self.CANDIDATE_PLACE_TERMS):
                continue
            if not any(term in sentence for term in self.UNSAFE_CONFIRMATION_TERMS):
                continue
            negated = re.search(
                r"\b(?:not|never|cannot|must not|should not|no)\b.{0,80}\b(?:confirmed|guaranteed) safe\b",
                sentence,
            )
            if not negated:
                unsafe_sentence = sentence
                break
        if unsafe_sentence:
            return self._result(
                "fail",
                "Assembly point wording",
                "Candidate assembly points should not be described as confirmed safe without local and official approval.",
            )
        return self._result(
            "pass",
            "Assembly point wording",
            "No obvious unsafe confirmation of candidate assembly points was detected.",
        )

    def _check_safety_boundaries(self, text):
        evaluation = evaluate_safety_boundaries(text)
        if evaluation["passed"]:
            return self._result(
                "pass",
                "Safety boundary assertions",
                "No high-confidence live-status, evacuation, unsafe-place or governance-removal assertion was detected.",
            )
        violations = evaluation["violations"]
        codes = sorted({item["code"] for item in violations})
        result = self._result(
            "fail",
            "Safety boundary assertions",
            "Remove or qualify prohibited operational assertions "
            f"({', '.join(codes)}). {len(violations)} privacy-minimised finding(s) were recorded; "
            "inspect the current in-memory report to locate the claims.",
        )
        result["privacy_minimised_findings"] = self._privacy_minimised_findings(violations)
        return result

    def _check_model_authored_urls(self, text):
        if not has_model_authored_url(text):
            return self._result(
                "pass",
                "Model-authored URLs",
                "The narrative contains no model-authored web links.",
            )
        return self._result(
            "fail",
            "Model-authored URLs",
            "Remove model-authored URLs; verified links are bound only in deterministic Evidence Tables.",
        )

    def _check_model_authored_raw_html(self, text):
        if not has_model_authored_raw_html(text):
            return self._result(
                "pass",
                "Model-authored raw HTML",
                "The narrative uses the governed Markdown-only format.",
            )
        return self._result(
            "fail",
            "Model-authored raw HTML",
            "Remove raw HTML tags and comments; use only the governed Markdown report format.",
        )

    def _check_unbound_attribution_markers(self, text, *, enforce):
        if not enforce:
            return self._result(
                "pass",
                "Unverified attribution markers",
                "No frozen source register was supplied; the legacy compatibility assessment does not bind labels.",
            )
        if not has_unbound_attribution_marker(text):
            return self._result(
                "pass",
                "Unverified attribution markers",
                "The narrative contains no residual unverified attribution-like markers.",
            )
        return self._result(
            "fail",
            "Unverified attribution markers",
            "Remove unverified or visually confusable attribution markers; only application-bound source labels "
            "are accepted.",
        )

    @staticmethod
    def _privacy_minimised_findings(violations):
        claims_by_code = defaultdict(list)
        for violation in violations:
            code = str(violation.get("code") or "unknown")
            excerpt = re.sub(r"\s+", " ", str(violation.get("excerpt") or "")).strip()
            claims_by_code[code].append(excerpt)
        return [
            {
                "code": code,
                "count": len(claims),
                "claim_hash": hashlib.sha256("\n".join(sorted(claims)).encode("utf-8")).hexdigest(),
            }
            for code, claims in sorted(claims_by_code.items())
        ]

    def _check_evidence_tables(self, text):
        lowered = text.lower()
        required = ["evidence tables", "selected geography", "community indicators", "official source register"]
        if all(term in lowered for term in required):
            return self._result(
                "pass", "Evidence tables", "The report includes deterministic evidence tables for review."
            )
        return self._result(
            "fail",
            "Evidence tables",
            "Add selected geography, community indicator and official source evidence tables.",
        )

    def _check_evidence_confidence(self, text):
        lowered = text.lower()
        required = ["evidence confidence and provenance", "o1", "p2", "r3", "a4", "u0"]
        if all(term in lowered for term in required):
            return self._result(
                "pass",
                "Evidence confidence",
                "The report distinguishes official references, processed data, rule inference, AI text and unverified inputs.",
            )
        return self._result(
            "warning",
            "Evidence confidence",
            "Add O1, P2, R3, A4 and U0 provenance labels and explain their review boundaries.",
        )

    def _check_human_review_status(self, text):
        lowered = text.lower()
        if "human review sign-off" in lowered and "draft" in lowered:
            return self._result(
                "pass",
                "Human review status",
                "The report includes a human review sign-off section and draft boundary.",
            )
        return self._result(
            "fail",
            "Human review status",
            "Add a human review sign-off section and keep unapproved outputs marked as drafts.",
        )

    def _extract_sections(self, text):
        sections = {}
        current = None
        current_level = None
        known_sections = {normalise_markdown_heading(heading) for heading in self.REQUIRED_SECTION_HEADINGS}
        for line in self._non_fenced_markdown_lines(text):
            match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
            if match:
                level = len(match.group(1))
                heading = normalise_markdown_heading(match.group(2))
                if heading in known_sections:
                    current = heading
                    current_level = level
                    sections.setdefault(current, [])
                elif current is not None and level > current_level:
                    sections[current].append(match.group(2).strip())
                else:
                    current = None
                    current_level = None
            elif current is not None:
                sections[current].append(line)
        return {heading: "\n".join(lines) for heading, lines in sections.items()}

    def _required_heading_counts(self, text):
        known_sections = {normalise_markdown_heading(heading) for heading in self.REQUIRED_SECTION_HEADINGS}
        counts = {heading: 0 for heading in known_sections}
        for line in self._non_fenced_markdown_lines(text):
            match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
            if not match:
                continue
            heading = normalise_markdown_heading(match.group(2))
            if heading in counts:
                counts[heading] += 1
        return counts

    @staticmethod
    def _non_fenced_markdown_lines(text):
        fence_character = None
        fence_length = 0
        for line in str(text or "").splitlines():
            fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fence_character is not None:
                marker = fence.group(1) if fence else ""
                suffix = fence.group(2) if fence else ""
                if marker.startswith(fence_character * fence_length) and not suffix.strip():
                    fence_character = None
                    fence_length = 0
                continue
            if fence:
                marker = fence.group(1)
                fence_character = marker[0]
                fence_length = len(marker)
                continue
            yield line

    def _result(self, status, name, detail):
        return {
            "status": status,
            "name": name,
            "detail": detail,
        }
