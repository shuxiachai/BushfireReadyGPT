import pytest

from src.agents.report_quality_agent import ReportQualityAgent
from src.current_report_structure import current_report_heading
from src.report_content_contract import evaluate_report_content_contract
from src.source_attribution import normalise_markdown_heading
from tests.support.report_fixtures import _valid_report

CANONICAL = "First Aid, Training and Exercises"
ALIAS = "First Aid, Training, and Exercises"


def test_alias_is_current_only_and_shared_by_counts_and_extraction():
    narrative, _analysis = _valid_report()
    narrative = narrative.replace(CANONICAL, ALIAS)
    agent = ReportQualityAgent()
    assert agent._required_heading_counts(narrative)[CANONICAL.lower()] == 1
    assert "First aid readiness" in agent._extract_sections(narrative)[CANONICAL.lower()]
    assert agent._check_sections(narrative)["status"] == "pass"
    assert normalise_markdown_heading(ALIAS) == ALIAS.lower()
    assert current_report_heading("First Aid Training and Exercises") != CANONICAL.lower()


@pytest.mark.parametrize("heading", [CANONICAL, ALIAS])
def test_alias_does_not_skip_local_proposal_safety_check(heading):
    checks = evaluate_report_content_contract(f"## 12. {heading}\nConduct training exercises.", {})
    local = next(item for item in checks if item["name"] == "Local proposal attribution")
    assert local["status"] == "fail"
    assert "local_task_requires_own_proposal_and_confirmer" in str(local)


def test_canonical_and_alias_are_duplicates_not_two_distinct_sections():
    narrative, _analysis = _valid_report()
    narrative += f"\n## 12. {ALIAS}\nAnother training section must not substitute for the single required section."
    agent = ReportQualityAgent()
    assert agent._required_heading_counts(narrative)[CANONICAL.lower()] == 2
    assert agent._check_sections(narrative)["status"] == "fail"


@pytest.mark.parametrize("replacement", [f"```markdown\n## 12. {ALIAS}\n```", f"## 12. {ALIAS}"])
def test_fenced_or_empty_alias_cannot_satisfy_required_substantive_section(replacement):
    narrative, _analysis = _valid_report()
    start = narrative.index(f"## 12. {CANONICAL}")
    end = narrative.index("## 13. Action Plan", start)
    narrative = narrative[:start] + replacement + "\n\n" + narrative[end:]
    assert ReportQualityAgent()._check_sections(narrative)["status"] == "fail"
