"""Checkout must preserve raw diagnostic hashes and canonical fixture line endings."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path("docs/diagnostics/form-context-cpu-2026-09-11.json")
FIXTURE = Path("data_australia/rag/form_evaluation_v1.json")
GIT = shutil.which("git")


@pytest.mark.skipif(GIT is None, reason="Git is required to exercise checkout conversion")
@pytest.mark.parametrize("autocrlf", ["true", "false"])
@pytest.mark.parametrize("fixture_line_endings", ["original", "crlf"])
def test_diagnostic_and_fixture_checkout_bytes(tmp_path, autocrlf, fixture_line_endings):
    repository = tmp_path / "isolated-repository"
    checkout = tmp_path / "fresh-checkout"
    repository.mkdir()
    checkout.mkdir()
    environment = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }

    def git(*arguments):
        return subprocess.run(
            [GIT, "-c", f"core.autocrlf={autocrlf}", "-c", f"core.attributesFile={os.devnull}", *arguments],
            cwd=repository,
            env=environment,
            check=True,
            capture_output=True,
            timeout=15,
        ).stdout

    git("init", "--quiet")
    # Use the working files, not HEAD: the recorded artifact bytes are the
    # authority, including when an earlier commit normalized them incorrectly.
    for relative in (Path(".gitattributes"), ARTIFACT, FIXTURE):
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)

    artifact_bytes = (ROOT / ARTIFACT).read_bytes()
    fixture_bytes = (ROOT / FIXTURE).read_bytes()
    fixture_lf = fixture_bytes.replace(b"\r\n", b"\n")
    if fixture_line_endings == "crlf":
        # Also exercise staging after a Windows editor changed only line endings.
        (repository / FIXTURE).write_bytes(fixture_lf.replace(b"\n", b"\r\n"))
    assert json.loads((repository / FIXTURE).read_bytes()) == json.loads(fixture_bytes)

    git("add", "--", ".gitattributes", ARTIFACT.as_posix(), FIXTURE.as_posix())
    staged_artifact = git("show", f":{ARTIFACT.as_posix()}")
    staged_fixture = git("show", f":{FIXTURE.as_posix()}")
    assert staged_artifact == artifact_bytes
    assert staged_fixture == fixture_lf

    # checkout-index materializes the index into an empty directory, exercising
    # real Git checkout filters without a commit, branch switch or file deletion.
    git("checkout-index", "--all", f"--prefix={checkout.as_posix()}/")
    checked_out_artifact = (checkout / ARTIFACT).read_bytes()
    checked_out_fixture = (checkout / FIXTURE).read_bytes()
    assert checked_out_artifact == artifact_bytes
    assert hashlib.sha256(checked_out_artifact).digest() == hashlib.sha256(artifact_bytes).digest()
    assert checked_out_fixture == fixture_lf
    assert b"\r" not in checked_out_fixture
