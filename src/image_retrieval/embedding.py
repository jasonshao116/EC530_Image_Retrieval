"""Deterministic embedding service for local image retrieval."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


DEFAULT_EMBEDDING_DIMENSION = 16
DEFAULT_MODEL = "hash-token-embedding-v1"


def tokens(value: str) -> list[str]:
    return [
        token.strip().lower()
        for token in value.replace("/", " ").replace("-", " ").replace("_", " ").split()
        if token.strip()
    ]


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    dimension: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "vector": self.vector,
            "model": self.model,
            "dimension": self.dimension,
        }


class EmbeddingService:
    """Small deterministic embedding service used by Push 8."""

    def __init__(
        self,
        *,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        model: str = DEFAULT_MODEL,
    ) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be at least 1")
        self.dimension = dimension
        self.model = model

    def embed_text(self, value: str) -> EmbeddingResult:
        vector = [0.0] * self.dimension
        for token in tokens(value):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:2], "big") % self.dimension
            sign = 1 if digest[2] % 2 == 0 else -1
            vector[bucket] += sign
        return EmbeddingResult(vector=vector, model=self.model, dimension=self.dimension)

    def embed_image(self, image: dict[str, Any]) -> EmbeddingResult:
        return self.embed_text(self.searchable_image_text(image))

    def searchable_image_text(self, image: dict[str, Any]) -> str:
        return " ".join(
            [
                image.get("storage_uri", ""),
                image.get("content_type", ""),
                " ".join(image.get("tags", [])),
            ]
        )
