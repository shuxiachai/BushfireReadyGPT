class RagError(ValueError):
    """Raised when the optional local RAG corpus or index is not trustworthy."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
