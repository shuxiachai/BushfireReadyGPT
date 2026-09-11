"""Runtime RAG state must not dirty provenance or publish private corpus bytes."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        ("data_australia/rag/.cpu-index-validation.lock.guard", True),
        ("data_australia/rag/.index-v4.lock.guard", True),
        ("data_australia/rag/index-v4/documents.jsonl", True),
        ("data_australia/rag/index-v4-next/manifest.json", True),
        ("data_australia/rag/form_evaluation_v1.json", False),
        ("data_australia/rag/sources.yml", False),
        ("data_australia/rag/operator-notes.guard", False),
    ],
)
def test_runtime_rag_paths_are_ignored_without_hiding_public_inputs(tmp_path, path, ignored):
    project = Path(__file__).resolve().parents[1]
    (tmp_path / ".gitignore").write_bytes((project / ".gitignore").read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True, timeout=10)
    result = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "--no-index", "-q", path],
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (0 if ignored else 1), result.stderr.decode(errors="replace")
