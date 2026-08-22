import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from pypdf import PdfReader

REQUIRED_REPORT_MARKERS = (
    "DRAFT STATUS NOTICE",
    "Evidence Tables",
    "Data Currency and Geographic Match",
    "Human Review Sign-off",
)


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def verify_sample_package(package_path, *, standalone_dir=None):
    """Verify one committed showcase package and return a concise result."""

    package_path = Path(package_path)
    if not package_path.is_file():
        raise ValueError(f"Sample package does not exist: {package_path}")
    try:
        with ZipFile(package_path) as archive:
            archive.testzip()
            names = archive.namelist()
            manifest = json.loads(archive.read("governance/package_manifest.json"))
            report_paths = _report_paths(names)
            _verify_manifest(archive, manifest, names)
            report_payloads = {suffix: archive.read(path) for suffix, path in report_paths.items()}
    except (BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f"Sample package is unreadable or malformed: {error}") from error

    markdown_text = report_payloads[".md"].decode("utf-8")
    pdf_pages, pdf_text = _verify_pdf(report_payloads[".pdf"])
    docx_paragraphs, docx_text = _verify_docx(report_payloads[".docx"])
    for marker in REQUIRED_REPORT_MARKERS:
        if marker not in markdown_text or marker not in pdf_text or marker not in docx_text:
            raise ValueError(f"Required report marker is missing from an export: {marker}")
    if standalone_dir is not None:
        _verify_standalone_reports(Path(standalone_dir), report_payloads)

    return {
        "package_schema": manifest.get("package_schema"),
        "included_files": len(names),
        "verified_hashes": len(manifest.get("artifact_hashes", {})),
        "pdf_pages": pdf_pages,
        "docx_paragraphs": docx_paragraphs,
        "report_id": manifest.get("context", {}).get("report_id"),
    }


def _report_paths(names):
    report_paths = {}
    for suffix in (".md", ".pdf", ".docx"):
        matches = [name for name in names if name.startswith("reports/") and name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {suffix} report in the sample package.")
        report_paths[suffix] = matches[0]
    return report_paths


def _verify_manifest(archive, manifest, names):
    if manifest.get("package_schema") != "pilot-export-v3":
        raise ValueError("Sample package schema is not pilot-export-v3.")
    if set(manifest.get("included_files", [])) != set(names):
        raise ValueError("Package manifest included_files does not match the ZIP contents.")
    artifact_hashes = manifest.get("artifact_hashes", {})
    if not artifact_hashes:
        raise ValueError("Package manifest contains no artifact hashes.")
    for path, expected_hash in artifact_hashes.items():
        if path not in names or sha256_bytes(archive.read(path)) != expected_hash:
            raise ValueError(f"Package artifact hash mismatch: {path}")


def _verify_pdf(payload):
    reader = PdfReader(BytesIO(payload))
    if not reader.pages:
        raise ValueError("PDF report has no pages.")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return len(reader.pages), text


def _verify_docx(payload):
    document = Document(BytesIO(payload))
    signoff_indexes = [
        index
        for index, paragraph in enumerate(document.paragraphs)
        if paragraph.text.strip() == "Human Review Sign-off"
    ]
    has_dedicated_page = False
    if len(signoff_indexes) == 1:
        signoff_index = signoff_indexes[0]
        heading = document.paragraphs[signoff_index]
        has_dedicated_page = heading.paragraph_format.page_break_before is True
        if signoff_index > 0:
            preceding = document.paragraphs[signoff_index - 1]
            has_dedicated_page = has_dedicated_page or bool(preceding._p.xpath(".//w:br[@w:type='page']"))
    if not has_dedicated_page:
        raise ValueError("DOCX Human Review Sign-off must start on a dedicated page.")
    text_parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            text_parts.extend(cell.text for cell in row.cells)
    return len(document.paragraphs), "\n".join(text_parts)


def _verify_standalone_reports(directory, report_payloads):
    expected = {
        ".md": directory / "cairns-council-report.md",
        ".pdf": directory / "cairns-council-report.pdf",
        ".docx": directory / "cairns-council-report.docx",
    }
    for suffix, path in expected.items():
        if not path.is_file() or path.read_bytes() != report_payloads[suffix]:
            raise ValueError(f"Standalone {suffix} report does not match the package: {path}")


def main():
    parser = argparse.ArgumentParser(description="Verify the committed BushfireReadyGPT showcase exports.")
    parser.add_argument(
        "package",
        nargs="?",
        default="examples/v0.3.0/cairns-council-pilot-package.zip",
    )
    parser.add_argument("--standalone-dir", default="examples/v0.3.0")
    args = parser.parse_args()
    result = verify_sample_package(args.package, standalone_dir=args.standalone_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
