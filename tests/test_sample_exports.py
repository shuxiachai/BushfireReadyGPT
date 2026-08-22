from pathlib import Path

from scripts.verify_sample_exports import verify_sample_package

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_committed_v030_showcase_exports_are_internally_consistent():
    sample_dir = PROJECT_ROOT / "examples" / "v0.3.0"

    result = verify_sample_package(
        sample_dir / "cairns-council-pilot-package.zip",
        standalone_dir=sample_dir,
    )

    assert result["package_schema"] == "pilot-export-v3"
    assert result["included_files"] == 11
    assert result["verified_hashes"] == 10
    assert result["pdf_pages"] >= 1
    assert result["report_id"]
