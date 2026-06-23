class ReportQualityAgent:
    """Checks generated reports against the project quality requirements."""

    REQUIRED_TERMS = [
        "Executive Summary",
        "Purpose",
        "Scope",
        "Selected Geography",
        "Data Sources",
        "Local Risk Context",
        "Evacuation",
        "Assembly Point",
        "Roles",
        "Communication",
        "First Aid",
        "Action Plan",
        "Checklist",
        "Official",
        "Evidence Tables",
        "ASGS",
        "Safety Disclaimer",
    ]

    OFFICIAL_SOURCE_TERMS = [
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

    def run(self, report_text):
        text = report_text or ""
        checks = [
            self._check_sections(text),
            self._check_official_sources(text),
            self._check_safety_disclaimer(text),
            self._check_emergency_number(text),
            self._check_action_plan(text),
            self._check_checklist(text),
            self._check_role_assignment(text),
            self._check_candidate_assembly_language(text),
            self._check_evidence_tables(text),
            self._check_human_review_status(text),
        ]

        passed = sum(1 for item in checks if item["status"] == "pass")
        warnings = sum(1 for item in checks if item["status"] == "warning")
        failed = sum(1 for item in checks if item["status"] == "fail")

        return {
            "checks": checks,
            "summary": {
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
                "total": len(checks),
            },
        }

    def _check_sections(self, text):
        missing = [section for section in self.REQUIRED_TERMS if section.lower() not in text.lower()]
        if not missing:
            return self._result("pass", "Required sections", "The report covers the main required sections.")
        return self._result("warning", "Required sections", "Potentially missing: " + ", ".join(missing))

    def _check_official_sources(self, text):
        found = [term for term in self.OFFICIAL_SOURCE_TERMS if term.lower() in text.lower()]
        if len(found) >= 4:
            return self._result("pass", "Official sources", "The report includes multiple official information sources.")
        return self._result(
            "warning",
            "Official sources",
            "Add the state fire service, local council, Bureau of Meteorology and 000 where relevant.",
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
        lowered = text.lower()
        if "action plan" in lowered and "day 1" in lowered:
            return self._result("pass", "Action plan", "The report includes a day-based action plan.")
        return self._result("warning", "Action plan", "The report should include a Day 1 style action plan.")

    def _check_checklist(self, text):
        lowered = text.lower()
        has_markdown_checkbox = "- [ ]" in text or "- [x]" in lowered
        if "checklist" in lowered and has_markdown_checkbox:
            return self._result("pass", "Checklist", "The report includes a checkable checklist.")
        return self._result("warning", "Checklist", "Use Markdown checkboxes for the checklist.")

    def _check_role_assignment(self, text):
        role_terms = ["roles", "teacher", "student", "first aid", "communication"]
        found = [term for term in role_terms if term in text.lower()]
        if len(found) >= 4:
            return self._result("pass", "Roles and responsibilities", "The report covers key role responsibilities.")
        return self._result(
            "warning",
            "Roles and responsibilities",
            "Add management, staff/teachers, students, wardens, first aiders and communications roles.",
        )

    def _check_candidate_assembly_language(self, text):
        lowered = text.lower()
        mentions_place = any(term in lowered for term in self.CANDIDATE_PLACE_TERMS)
        confirms_safety = any(term in lowered for term in self.UNSAFE_CONFIRMATION_TERMS)
        if mentions_place and confirms_safety:
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

    def _check_evidence_tables(self, text):
        lowered = text.lower()
        required = ["evidence tables", "selected geography", "community indicators", "official source register"]
        if all(term in lowered for term in required):
            return self._result("pass", "Evidence tables", "The report includes deterministic evidence tables for review.")
        return self._result(
            "warning",
            "Evidence tables",
            "Add selected geography, community indicator and official source evidence tables.",
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
            "warning",
            "Human review status",
            "Add a human review sign-off section and keep unapproved outputs marked as drafts.",
        )

    def _result(self, status, name, detail):
        return {
            "status": status,
            "name": name,
            "detail": detail,
        }
