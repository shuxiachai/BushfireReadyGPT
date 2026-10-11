"""Complete synthetic assessments for tests of repair-loop control flow."""

from src.report_repair_guard import REQUIRED_REPAIR_CHECKS


def repair_quality(*, passed=False, total_words=700, model_words=400, statuses=None):
    """Supply canonical comparison data without replacing production assessment."""
    statuses = dict(statuses or {})
    statuses.setdefault("Required sections", "pass" if passed else "fail")
    statuses.setdefault("Narrative word budget", "pass" if 650 <= total_words <= 800 else "fail")
    statuses.setdefault("Model prose word budget", "pass" if model_words >= 300 else "fail")
    checks = [
        {"name": name, "status": statuses.get(name, "pass")}
        for name in sorted(REQUIRED_REPAIR_CHECKS | statuses.keys())
    ]
    for check in checks:
        if check["name"] == "Narrative word budget":
            check["word_count"] = total_words
        elif check["name"] == "Model prose word budget":
            check["word_count"] = model_words
    return {
        "checks": checks,
        "approval_gate": {
            "passed": passed,
            "blocking_failures": [
                {"name": check["name"], "detail": "Synthetic mandatory failure."}
                for check in checks
                if check["status"] == "fail"
            ],
        },
    }
