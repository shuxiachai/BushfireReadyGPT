"""Private deploy exports use committed bytes and one bounded corpus only.

Fixed Git subprocess commands operate only on temporary test repositories.
"""

import json
import shutil
import subprocess  # nosec B404

import pytest

from scripts import prepare_railway_context as context
from src.corpus_bundle import CorpusBundleError, create_test_corpus_bundle, validate_corpus_bundle


def _git(repo, *arguments):
    return subprocess.run(  # nosec B603
        [shutil.which("git"), "-C", str(repo), *arguments],
        capture_output=True,
        check=True,
    ).stdout


def _commit(repo):
    _git(repo, "add", ".")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", "Fixture snapshot")


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Fixture Author")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    for filename in context._REQUIRED_FILES:
        (repo / filename).write_text(f"committed {filename}\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("COMMITTED = True\n", encoding="utf-8")
    _commit(repo)
    corpus = tmp_path / "bundle"
    create_test_corpus_bundle(corpus)
    return repo, corpus, tmp_path / "prepared"


def test_exports_only_head_blobs_and_validated_bundle(inputs):
    repo, corpus, output = inputs
    (repo / "src" / "app.py").write_text("UNCOMMITTED_PASSWORD = 'do not export'\n", encoding="utf-8")
    (repo / "src" / "unexpected.py").write_text("untracked workstation data", encoding="utf-8")
    (repo / ".env").write_text("DEEPSEEK_API_KEY=never-export-this", encoding="utf-8")
    summary = context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert (output / "src" / "app.py").read_text() == "COMMITTED = True\n"
    assert not (output / "src" / "unexpected.py").exists()
    assert not (output / ".env").exists()
    assert not (output / ".git").exists()
    assert summary["commit"] == _git(repo, "rev-parse", "HEAD").decode().strip()
    assert summary["snapshot_mode"] == "committed_HEAD_blobs_only"
    assert summary["uploaded"] is False
    installed = validate_corpus_bundle(output / "deployment_corpus")
    assert installed["manifest_sha256"] == summary["corpus_manifest_sha256"]
    assert summary["source_count"] == 1
    assert summary["file_count"] == sum(path.is_file() for path in output.rglob("*"))
    manifest = json.loads((output / context.CONTEXT_MANIFEST).read_text())
    assert "files" in manifest and "files" not in summary
    assert "never-export-this" not in json.dumps(manifest)


def test_staged_additions_and_deletions_do_not_modify_head_snapshot(inputs):
    repo, corpus, output = inputs
    _git(repo, "rm", "src/app.py")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "new.py").write_text("staged only", encoding="utf-8")
    _git(repo, "add", "src/new.py")
    context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert (output / "src" / "app.py").is_file()
    assert not (output / "src" / "new.py").exists()


def test_allowlist_excludes_raw_maps_personal_files_and_media(inputs):
    repo, corpus, output = inputs
    excluded = [
        "data_australia/raw/download.csv",
        "data_australia/rag/raw/source.html",
        "data_australia/rag/index/manifest.json",
        "data_australia/rag/models/model.onnx",
        "data_australia/processed/sa2_boundaries_all.geojson",
        "data_australia/processed/sa2_profiles_all.csv",
        "data_australia/processed/sa2_map_bundle.json",
        "data_australia/processed/sa2_boundaries_by_state/qld.geojson",
        "docs/assets/movie.webm",
        "项目描述说明.md",
        ".streamlit/secrets.toml",
        ".env",
        "output/private.txt",
        "chat_history/session.json",
    ]
    included = [
        "data_australia/rag/sources.yml",
        "data_australia/rag/evaluation.json",
        "data_australia/rag/report_evaluation-v0.6.0.json",
        "data_australia/rag/report_red_team-v0.6.0.json",
        "data_australia/processed/community_profiles.csv",
        "docs/DEPLOYMENT.md",
        "examples/report.md",
        ".streamlit/config.toml",
    ]
    for relative in excluded + included:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    _commit(repo)
    context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert all(not (output / relative).exists() for relative in excluded)
    assert all((output / relative).is_file() for relative in included)


@pytest.mark.parametrize(
    "relative",
    [
        "src/.env.production",
        "src/secrets.toml",
        "scripts/credentials.json",
        "docs/private_key.pem",
        "src/id_ed25519",
        "examples/key.pfx",
        "src/.hidden/file.py",
    ],
)
def test_rejects_secret_like_committed_paths(inputs, relative):
    repo, corpus, output = inputs
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sensitive fixture", encoding="utf-8")
    _commit(repo)
    with pytest.raises(context.ContextPreparationError, match="secret-like or hidden"):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert not output.exists()


def test_rejects_committed_symlink_without_reading_its_target(inputs):
    repo, corpus, output = inputs
    # Writing a symlink entry directly also tests Windows hosts without symlink privileges.
    object_id = _git(repo, "rev-parse", "HEAD:src/app.py").decode().strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{object_id},src/linked.py")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", "Symlink fixture")
    with pytest.raises(context.ContextPreparationError, match="regular files"):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert not output.exists()


def test_existing_destination_is_never_overwritten(inputs):
    repo, corpus, output = inputs
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(context.ContextPreparationError, match="already exists"):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("location", ["repo", "ancestor", "source", "git", "corpus_child"])
def test_rejects_unsafe_destination_locations(inputs, location):
    repo, corpus, _ = inputs
    targets = {
        "repo": repo,
        "ancestor": repo.parent,
        "source": repo / "src" / "deploy",
        "git": repo / ".git" / "deploy",
        "corpus_child": corpus / "deploy",
    }
    with pytest.raises(context.ContextPreparationError):
        context.prepare_railway_context(corpus, targets[location], repo_dir=repo)


def test_default_destination_is_isolated_under_output(inputs):
    repo, corpus, _ = inputs
    context.prepare_railway_context(corpus, repo_dir=repo)
    assert (repo / "output" / "railway-private-context" / context.CONTEXT_MANIFEST).is_file()


def test_invalid_or_extra_corpus_files_do_not_create_context(inputs):
    repo, corpus, output = inputs
    (corpus / "unexpected.txt").write_text("not declared", encoding="utf-8")
    with pytest.raises(CorpusBundleError):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert not output.exists()


def test_context_size_limit_prevents_publication(inputs, monkeypatch):
    repo, corpus, output = inputs
    monkeypatch.setattr(context, "MAX_CONTEXT_BYTES", 1)
    with pytest.raises(context.ContextPreparationError, match="size limit"):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert not output.exists()


def test_new_destination_appearing_during_staging_is_not_replaced(inputs, monkeypatch):
    repo, corpus, output = inputs
    original = context._export_blobs

    def race(*args):
        result = original(*args)
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        return result

    monkeypatch.setattr(context, "_export_blobs", race)
    with pytest.raises(FileExistsError):
        context.prepare_railway_context(corpus, output, repo_dir=repo)
    assert list(output.iterdir()) == [output / "keep.txt"]


def test_cli_prints_only_safe_summary(inputs, monkeypatch, capsys):
    _, corpus, output = inputs
    monkeypatch.setattr(context, "prepare_railway_context", lambda *args: {"source_count": 1, "uploaded": False})
    assert context.main(["--corpus", str(corpus), "--output", str(output)]) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out) == {"source_count": 1, "uploaded": False}


def test_cli_does_not_echo_sensitive_exception_text(inputs, monkeypatch, capsys):
    _, corpus, output = inputs

    def fail(*args):
        raise ValueError("do not print a hypothetical secret")

    monkeypatch.setattr(context, "prepare_railway_context", fail)
    assert context.main(["--corpus", str(corpus), "--output", str(output)]) == 1
    printed = capsys.readouterr()
    assert "hypothetical secret" not in printed.err
    assert "ValueError" in printed.err
