import pytest

from src import report_generation_quality as quality


def test_generation_and_repair_share_one_bounded_policy(monkeypatch):
    assessments = iter(
        [
            {"approval_gate": {"passed": False, "blocking_failures": [{"name": "Structure"}]}},
            {"approval_gate": {"passed": True, "blocking_failures": []}},
        ]
    )
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda _text, _analysis: next(assessments))
    monkeypatch.setattr(
        quality,
        "build_report_repair_prompt",
        lambda original, previous, _result: f"repair::{original}::{previous}",
    )
    calls = []

    def generate(prompt, attempt_number, is_repair):
        calls.append((prompt, attempt_number, is_repair))
        return "first draft" if attempt_number == 1 else "replacement draft"

    narrative, result, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        {"profile": {}},
        generate,
    )

    assert narrative == "replacement draft"
    assert result["approval_gate"]["passed"] is True
    assert attempts == 2
    assert calls == [
        ("governed prompt", 1, False),
        ("repair::governed prompt::first draft", 2, True),
    ]


def test_generation_repairs_stop_at_configured_limit(monkeypatch):
    failed = {"approval_gate": {"passed": False, "blocking_failures": []}}
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda _text, _analysis: failed)
    monkeypatch.setattr(quality, "build_report_repair_prompt", lambda *_args: "repair")
    calls = []

    narrative, result, attempts = quality.generate_narrative_with_repairs(
        "prompt",
        {},
        lambda prompt, attempt, repair: calls.append((prompt, attempt, repair)) or f"draft-{attempt}",
        max_repair_attempts=2,
    )

    assert narrative == "draft-3"
    assert result is failed
    assert attempts == 3
    assert [call[1] for call in calls] == [1, 2, 3]


@pytest.mark.parametrize("limit", [-1, True, 1.5, "2"])
def test_generation_repair_limit_must_be_a_non_negative_integer(limit):
    with pytest.raises(ValueError, match="non-negative integer"):
        quality.generate_narrative_with_repairs("prompt", {}, lambda *_args: "draft", max_repair_attempts=limit)


def test_generation_callback_must_be_callable():
    with pytest.raises(TypeError, match="must be callable"):
        quality.generate_narrative_with_repairs("prompt", {}, None)
