"""In-memory vector index service for local similarity search."""

from __future__ import annotations

import copy
import json
import math
import os
from typing import Any

import redis

from .config import load_dotenv


DEFAULT_INDEX_NAME = "image-embeddings-v1"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class VectorDimensionError(ValueError):
    """Raised when a vector does not match the index dimension."""


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class VectorIndexService:
    """Small vector index service used by Push 9."""

    def __init__(
        self,
        *,
        dimension: int,
        index_name: str = DEFAULT_INDEX_NAME,
    ) -> None:
        if dimension < 1:
            raise ValueError("Vector dimension must be at least 1")
        self.dimension = dimension
        self.index_name = index_name
        self._records: dict[str, dict[str, Any]] = {}

    @property
    def vector_count(self) -> int:
        return len(self._records)

    def upsert(
        self,
        image_id: str,
        vector: list[float],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_vector(vector)
        record = {
            "image_id": image_id,
            "vector": list(vector),
            "metadata": copy.deepcopy(metadata or {}),
        }
        self._records[image_id] = record
        return copy.deepcopy(record)

    def get(self, image_id: str) -> dict[str, Any] | None:
        record = self._records.get(image_id)
        return copy.deepcopy(record) if record else None

    def delete(self, image_id: str) -> bool:
        return self._records.pop(image_id, None) is not None

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        *,
        exclude_image_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_vector(query_vector)
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        scored_matches = [
            (image_id, cosine_similarity(query_vector, record["vector"]))
            for image_id, record in self._records.items()
            if image_id != exclude_image_id
        ]
        scored_matches.sort(key=lambda match: match[1], reverse=True)

        results = []
        for rank, (image_id, score) in enumerate(scored_matches[:top_k], start=1):
            record = self._records[image_id]
            results.append(
                {
                    "image_id": image_id,
                    "score": round(score, 4),
                    "rank": rank,
                    "metadata": copy.deepcopy(record["metadata"]),
                }
            )
        return results

    def stats(self) -> dict[str, Any]:
        return {
            "index_name": self.index_name,
            "dimension": self.dimension,
            "vector_count": self.vector_count,
        }

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimension:
            raise VectorDimensionError(
                f"Expected vector dimension {self.dimension}, got {len(vector)}"
            )


class RedisVectorIndexService:
    """Redis-backed vector and embedding store with local cosine search."""

    def __init__(
        self,
        redis_url: str = DEFAULT_REDIS_URL,
        *,
        dimension: int,
        index_name: str = DEFAULT_INDEX_NAME,
        namespace: str = "image-retrieval",
        client: Any | None = None,
    ) -> None:
        if dimension < 1:
            raise ValueError("Vector dimension must be at least 1")
        self.client = client or redis.Redis.from_url(redis_url, decode_responses=True)
        self.dimension = dimension
        self.index_name = index_name
        self.namespace = namespace.strip(":")
        self.vectors_key = f"{self.namespace}:vectors"
        self.embeddings_key = f"{self.namespace}:embeddings"

    @property
    def vector_count(self) -> int:
        return int(self.client.hlen(self.vectors_key))

    def upsert(
        self,
        image_id: str,
        vector: list[float],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_vector(vector)
        record = {
            "image_id": image_id,
            "vector": list(vector),
            "metadata": copy.deepcopy(metadata or {}),
        }
        payload = json.dumps(record, separators=(",", ":"), sort_keys=True)
        self.client.hset(self.vectors_key, image_id, payload)
        self.client.hset(
            self.embeddings_key,
            image_id,
            json.dumps(
                {
                    "image_id": image_id,
                    "embedding": list(vector),
                    "dimension": self.dimension,
                    "index_name": self.index_name,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        return copy.deepcopy(record)

    def get(self, image_id: str) -> dict[str, Any] | None:
        raw_record = self.client.hget(self.vectors_key, image_id)
        if raw_record is None:
            return None
        return json.loads(raw_record)

    def delete(self, image_id: str) -> bool:
        removed = int(self.client.hdel(self.vectors_key, image_id))
        self.client.hdel(self.embeddings_key, image_id)
        return removed > 0

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        *,
        exclude_image_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_vector(query_vector)
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        scored_matches = []
        for image_id, raw_record in self.client.hgetall(self.vectors_key).items():
            if image_id == exclude_image_id:
                continue
            record = json.loads(raw_record)
            scored_matches.append((image_id, cosine_similarity(query_vector, record["vector"]), record))
        scored_matches.sort(key=lambda match: match[1], reverse=True)

        results = []
        for rank, (image_id, score, record) in enumerate(scored_matches[:top_k], start=1):
            results.append(
                {
                    "image_id": image_id,
                    "score": round(score, 4),
                    "rank": rank,
                    "metadata": copy.deepcopy(record["metadata"]),
                }
            )
        return results

    def stats(self) -> dict[str, Any]:
        return {
            "index_name": self.index_name,
            "dimension": self.dimension,
            "vector_count": self.vector_count,
            "storage": "redis",
        }

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimension:
            raise VectorDimensionError(
                f"Expected vector dimension {self.dimension}, got {len(vector)}"
            )


def create_vector_index_from_env(
    *,
    dimension: int,
    index_name: str = DEFAULT_INDEX_NAME,
) -> VectorIndexService | RedisVectorIndexService:
    """Create the configured vector index.

    Set IMAGE_RETRIEVAL_VECTOR_INDEX=redis and REDIS_URL to persist vectors and
    embeddings in Redis.
    """

    load_dotenv()
    backend = os.getenv("IMAGE_RETRIEVAL_VECTOR_INDEX", "memory").strip().lower()
    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        namespace = os.getenv("REDIS_VECTOR_NAMESPACE") or os.getenv("REDIS_NAMESPACE", "image-retrieval")
        return RedisVectorIndexService(
            redis_url,
            dimension=dimension,
            index_name=index_name,
            namespace=namespace,
        )
    return VectorIndexService(dimension=dimension, index_name=index_name)
