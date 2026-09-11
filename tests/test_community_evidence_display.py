"""Evidence Trail must distinguish unknown percentages from observed zero."""

import json
from unittest.mock import MagicMock

import pytest

from src.ui import review_views


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", float("nan"), "NaN", float("inf"), "-inf", True, False, "unknown", "To be confirmed", -1, 101],
)
def test_missing_or_invalid_percentage_has_no_percent_suffix(value):
    assert review_views._community_evidence_value(value, "%") == "To be confirmed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0%"), (0.0, "0.0%"), ("0", "0%"), ("0.0", "0.0%"), (16.5, "16.5%"), (" 16.5 ", "16.5%"), (100, "100%")],
)
def test_known_percentage_including_zero_keeps_its_value(value, expected):
    assert review_views._community_evidence_value(value, "%") == expected


def _render(monkeypatch, indicators):
    streamlit = MagicMock()
    monkeypatch.setattr(review_views, "st", streamlit)
    review_views._render_community_evidence({"matched_location": "Synthetic community", "indicators": indicators})
    return [call.args[0] for call in streamlit.markdown.call_args_list]


@pytest.mark.parametrize("value", [None, "", float("nan")])
def test_rendered_missing_percentages_are_explicit_and_do_not_mutate_analysis(monkeypatch, value):
    indicators = {
        "older_people_pct": value,
        "no_car_households_pct": value,
        "language_other_than_english_pct": value,
        "language_support_needed": "unknown",
        "population": value,
    }
    before = json.dumps(indicators, sort_keys=True)
    rendered = _render(monkeypatch, indicators)
    for label in (
        "Older people percentage",
        "No-car household percentage",
        "Language other than English at home",
        "Population",
    ):
        assert f"- **{label}:** To be confirmed" in rendered
    assert "- **Language support need:** unknown" in rendered
    assert not any("%" in line for line in rendered)
    assert json.dumps(indicators, sort_keys=True) == before


def test_rendered_zero_percentages_are_not_dropped_as_optional_falsy_values(monkeypatch):
    indicators = {
        "older_people_pct": 0,
        "no_car_households_pct": "0",
        "language_other_than_english_pct": 0.0,
        "matched_sa2_count": 0,
        "population": 0,
    }
    rendered = _render(monkeypatch, indicators)
    assert "- **Older people percentage:** 0%" in rendered
    assert "- **No-car household percentage:** 0%" in rendered
    assert "- **Language other than English at home:** 0.0%" in rendered
    assert "- **Matched SA2 count:** 0" in rendered
    assert "- **Population:** 0" in rendered
    assert indicators["language_other_than_english_pct"] == 0.0


def test_absent_optional_indicators_remain_absent(monkeypatch):
    rendered = _render(monkeypatch, {})
    assert not any("Language other than English at home" in line for line in rendered)
    assert "- **Older people percentage:** To be confirmed" in rendered
    assert "- **No-car household percentage:** To be confirmed" in rendered
