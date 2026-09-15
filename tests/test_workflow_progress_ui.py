from src.ui import workflow_progress as progress_module


class _Status:
    def __init__(self):
        self.updates = []
        self.lines = []

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def write(self, text):
        self.lines.append(text)


def test_progress_uses_actual_stage_and_attempt_with_measured_elapsed(monkeypatch):
    clock = iter([10.0, 12.5, 14.0])
    monkeypatch.setattr(progress_module.time, "perf_counter", lambda: next(clock))
    status = _Status()
    progress = progress_module.WorkflowProgress(status, "Generate")
    progress({"event": "stage_started", "stage": "model_repair", "attempt": 2, "request_kind": "protocol_retry"})
    progress({"event": "stage_finished", "stage": "model_repair", "stage_elapsed_ms": 1500})
    progress.finish(error=True)
    assert status.updates[0]["label"] == "Protocol retry attempt 2 · 2.5s elapsed"
    assert status.lines == ["Retrying the model request: 1.5s"]
    assert status.updates[-1] == {"label": "Action needs attention · 4.0s", "state": "error", "expanded": True}


def test_progress_ignores_unrecognised_or_nonfinite_event_fields():
    status = _Status()
    progress = progress_module.WorkflowProgress(status, "Generate")
    progress({"event": "stage_started", "stage": "PRIVATE REQUEST CONTENT"})
    for duration in (float("nan"), float("inf"), -1, True, "private"):
        progress({"event": "stage_finished", "stage": "model_generation", "stage_elapsed_ms": duration})
    assert status.updates == []
    assert status.lines == []
