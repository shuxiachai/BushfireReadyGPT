"""Narrow heading identities for the current governed report policy only."""

from src.source_attribution import normalise_markdown_heading


def current_report_heading(value):
    """Recognise the one supported Oxford-comma variant without fuzzy matching."""
    heading = normalise_markdown_heading(value)
    if heading == "first aid, training, and exercises":
        return "first aid, training and exercises"
    return heading
