import re

DEFAULT_REPORT_TITLE = "Australian Bushfire Preparedness Report"


def plain_markdown_text(text):
    text = re.sub(r"^#+\s*", "", text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def _is_structural_title(text):
    normalized = re.sub(r"^\d+[.)]?\s*", "", plain_markdown_text(text)).strip().lower()
    return normalized == "title"


def extract_report_title(markdown_text):
    lines = markdown_text.splitlines()

    # Governed reports use a structural "1. Title" section. The actual title is
    # the first non-heading value after that section, not either heading label.
    for index, raw_line in enumerate(lines):
        if not raw_line.strip().startswith("#") or not _is_structural_title(raw_line):
            continue
        for candidate in lines[index + 1 :]:
            candidate = candidate.strip()
            if not candidate or (candidate.startswith("#") and _is_structural_title(candidate)):
                continue
            if candidate.startswith("#"):
                break
            title = plain_markdown_text(candidate)
            if title:
                return title

    # Simpler reports may put the real title directly in their first heading.
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("#") and not _is_structural_title(line):
            title = plain_markdown_text(line)
            if title and title.lower() != "bushfirereadygpt report":
                return title

    for raw_line in lines:
        line = plain_markdown_text(raw_line)
        if line and len(line) <= 120 and "draft status notice" not in line.lower():
            return line
    return DEFAULT_REPORT_TITLE


def extract_report_metadata(markdown_text):
    title = extract_report_title(markdown_text)
    location = None
    audience = None

    for raw_line in markdown_text.splitlines():
        line = plain_markdown_text(raw_line)
        if location is None:
            location_match = re.search(
                r"\blocation\s*:\s*(.+?)(?=\s*;\s*audience\s*:|$)",
                line,
                re.IGNORECASE,
            )
            if location_match:
                location = location_match.group(1).strip()
        if audience is None:
            audience_match = re.search(r"\baudience\s*:\s*(.+)$", line, re.IGNORECASE)
            if audience_match:
                audience = audience_match.group(1).strip()
        if location and audience:
            break

    if location is None:
        title_location = re.search(
            r"\b(?:report|plan)\s+for\s+(.+?)\s*[-–—]\s*draft\b",
            title,
            re.IGNORECASE,
        )
        if title_location:
            location = title_location.group(1).strip()

    if audience is None:
        summary_audience = re.search(
            r"\baimed at supporting\s+(.+?)(?:\s+in\s+(?:their|its)\b|[.])",
            markdown_text,
            re.IGNORECASE | re.DOTALL,
        )
        if summary_audience:
            audience = " ".join(summary_audience.group(1).split())

    return {
        "title": title,
        "location": location or "To be confirmed",
        "audience": audience or "To be confirmed",
    }
