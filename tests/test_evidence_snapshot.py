from src.ui.review_views import build_evidence_selection_messages, resolve_evidence_snapshot


def test_report_bound_evidence_snapshot_wins_over_live_state_and_marks_pending_selection():
    frozen_analysis = {"profile": {"location": "Cairns, Queensland"}}
    live_analysis = {"profile": {"location": "Brisbane, Queensland"}}
    frozen_selection = {"state": "Queensland", "level": "SA4", "area_name": "Cairns"}
    current_selection = {"state": "Queensland", "level": "SA4", "area_name": "Brisbane"}

    snapshot = resolve_evidence_snapshot(
        {"id": "report-1", "analysis": frozen_analysis, "area_selection": frozen_selection},
        live_analysis,
        current_selection,
    )
    caption, notice = build_evidence_selection_messages(snapshot)

    assert snapshot["analysis"] is frozen_analysis
    assert snapshot["frozen_area_selection"] == frozen_selection
    assert snapshot["current_area_selection"] == current_selection
    assert snapshot["selection_changed"] is True
    assert caption == "Map selection used for this report: Queensland / SA4 / Cairns"
    assert "will only be used for the next regenerated report" in notice
    assert "Queensland / SA4 / Brisbane" in notice


def test_report_bound_evidence_snapshot_does_not_warn_when_selection_is_unchanged():
    selection = {"state": "Tasmania", "level": "SA4", "area_name": "Hobart"}
    snapshot = resolve_evidence_snapshot(
        {"id": "report-1", "analysis": {"profile": {}}, "area_selection": selection},
        {"profile": {"location": "live-state"}},
        dict(selection),
    )

    caption, notice = build_evidence_selection_messages(snapshot)

    assert snapshot["selection_changed"] is False
    assert caption == "Map selection used for this report: Tasmania / SA4 / Hobart"
    assert notice is None


def test_unbound_evidence_snapshot_falls_back_to_live_analysis_and_current_selection():
    live_analysis = {"profile": {"location": "Darwin, Northern Territory"}}
    current_selection = {"state": "Northern Territory", "level": "SA4", "area_name": "Darwin"}

    snapshot = resolve_evidence_snapshot(None, live_analysis, current_selection)
    caption, notice = build_evidence_selection_messages(snapshot)

    assert snapshot["analysis"] is live_analysis
    assert snapshot["frozen_area_selection"] == current_selection
    assert snapshot["selection_changed"] is False
    assert caption == "Current map selection for this analysis: Northern Territory / SA4 / Darwin"
    assert notice is None


def test_report_without_frozen_analysis_does_not_fall_back_to_unbound_live_analysis():
    snapshot = resolve_evidence_snapshot(
        {"id": "legacy-report", "area_selection": None},
        {"profile": {"location": "Unbound live state"}},
        None,
    )

    assert snapshot["report_bound"] is True
    assert snapshot["analysis"] is None
