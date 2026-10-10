"""Current-only content-free admission diagnostic; historical failures stay frozen."""

from src.model_response import ModelResponseError


class SectionProtocolError(ModelResponseError):
    """Reject malformed section prose without retaining returned content."""

    def __init__(self):
        super().__init__("invalid")
        self.reason = "section_protocol"
        self.code = "model_response_section_protocol"
        self.retryable = True
        self.args = ("The model did not return the required section-prose object; no report was accepted.",)
