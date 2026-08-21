from __future__ import annotations

import math

import requests

from src.rag.errors import RagError


class OllamaEmbeddingClient:
    def __init__(self, base_url, model, *, timeout_seconds=60, batch_size=16):
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model)
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size

    def embed(self, texts):
        values = [str(text or "").strip() for text in texts]
        if not values or any(not value for value in values):
            raise RagError("rag_embedding_invalid", "Embedding input must contain non-empty text.")
        result = []
        for index in range(0, len(values), self.batch_size):
            batch = values[index : index + self.batch_size]
            try:
                response = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=(5, self.timeout_seconds),
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as error:
                raise RagError(
                    "rag_embedding_unavailable",
                    f"The local Ollama embedding model '{self.model}' is unavailable.",
                ) from error
            embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise RagError("rag_embedding_invalid", "Ollama returned an invalid embedding batch.")
            for vector in embeddings:
                if (
                    not isinstance(vector, list)
                    or not vector
                    or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in vector)
                    or any(not math.isfinite(float(item)) for item in vector)
                ):
                    raise RagError("rag_embedding_invalid", "Ollama returned an invalid embedding vector.")
                result.append([float(item) for item in vector])
        dimensions = {len(vector) for vector in result}
        if len(dimensions) != 1:
            raise RagError("rag_embedding_invalid", "Ollama returned inconsistent embedding dimensions.")
        return result
