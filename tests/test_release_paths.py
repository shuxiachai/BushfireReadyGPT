from pathlib import Path

import pytest

from scripts.release_paths import (
    ReleasePathError,
    release_version_tuple,
    resolve_release_directory,
    validate_release_version,
)


@pytest.mark.parametrize(
    "value",
    ("v0.6.0", "0.6", "0.6.0-rc1", "0.06.0", "../0.6.0", "", " 0.6.0"),
)
def test_release_version_rejects_noncanonical_or_path_like_values(value):
    with pytest.raises(ReleasePathError, match="major.minor.patch"):
        validate_release_version(value)


def test_release_directory_rejects_relative_and_absolute_path_escape(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")

    with pytest.raises(ReleasePathError, match="inside the project root"):
        resolve_release_directory(tmp_path, release_dir=Path("..") / "outside")

    with pytest.raises(ReleasePathError, match="inside the project root"):
        resolve_release_directory(tmp_path, release_dir=tmp_path.parent / "outside")


def test_release_directory_accepts_a_repository_contained_override(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.6.0"\n', encoding="utf-8")

    version, directory = resolve_release_directory(
        tmp_path,
        release_version="0.5.0",
        release_dir="release-evidence/archived-v050",
    )

    assert version == "0.5.0"
    assert directory == tmp_path / "release-evidence/archived-v050"


def test_release_version_tuple_is_numeric_not_lexicographic():
    assert release_version_tuple("0.10.0") > release_version_tuple("0.6.0")
