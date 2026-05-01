"""Vector index services for local similarity search."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

import redis

from .config import load_dotenv


DEFAULT_INDEX_NAME = "image-embeddings-v1"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_FAISS_INDEX_PATH = "data/faiss/image_embeddings.faiss"
DEFAULT_FAISS_METADATA_PATH = "data/faiss/image_embeddings.metadata.json"


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


class FAISSVectorIndexService:
    """FAISS-backed vector index with JSON metadata persistence."""

    def __init__(
        self,
        *,
        dimension: int,
        index_name: str = DEFAULT_INDEX_NAME,
        index_path: Path | str = DEFAULT_FAISS_INDEX_PATH,
        metadata_path: Path | str = DEFAULT_FAISS_METADATA_PATH,
    ) -> None:
        if dimension < 1:
            raise ValueError("Vector dimension must be at least 1")
        self.faiss, self.np = self._load_dependencies()
        self.dimension = dimension
        self.index_name = index_name
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self._records: dict[str, dict[str, Any]] = {}
        self._image_ids: list[str] = []
        self._index = self.faiss.IndexFlatIP(self.dimension)
        self._load()

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
        self._rebuild_index()
        self._persist()
        return copy.deepcopy(record)

    def get(self, image_id: str) -> dict[str, Any] | None:
        record = self._records.get(image_id)
        return copy.deepcopy(record) if record else None

    def delete(self, image_id: str) -> bool:
        if image_id not in self._records:
            return False
        del self._records[image_id]
        self._rebuild_index()
        self._persist()
        return True

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
        if self.vector_count == 0:
            return []

        query = self._as_normalized_matrix([query_vector])
        scores, indexes = self._index.search(query, self.vector_count)

        results = []
        for score, index_position in zip(scores[0], indexes[0]):
            if index_position < 0:
                continue
            image_id = self._image_ids[int(index_position)]
            if image_id == exclude_image_id:
                continue
            record = self._records[image_id]
            results.append(
                {
                    "image_id": image_id,
                    "score": round(float(score), 4),
                    "rank": len(results) + 1,
                    "metadata": copy.deepcopy(record["metadata"]),
                }
            )
            if len(results) == top_k:
                break
        return results

    def stats(self) -> dict[str, Any]:
        return {
            "index_name": self.index_name,
            "dimension": self.dimension,
            "vector_count": self.vector_count,
            "storage": "faiss",
            "index_path": str(self.index_path),
            "metadata_path": str(self.metadata_path),
        }

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimension:
            raise VectorDimensionError(
                f"Expected vector dimension {self.dimension}, got {len(vector)}"
            )

    def _as_normalized_matrix(self, vectors: list[list[float]]) -> Any:
        matrix = self.np.asarray(vectors, dtype="float32")
        norms = self.np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return matrix / norms

    def _rebuild_index(self) -> None:
        self._image_ids = list(self._records)
        self._index = self.faiss.IndexFlatIP(self.dimension)
        if not self._image_ids:
            return
        matrix = self._as_normalized_matrix(
            [self._records[image_id]["vector"] for image_id in self._image_ids]
        )
        self._index.add(matrix)

    def _load(self) -> None:
        if not self.metadata_path.exists():
            return
        payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if int(payload.get("dimension", self.dimension)) != self.dimension:
            raise VectorDimensionError(
                f"Expected FAISS metadata dimension {self.dimension}, got {payload.get('dimension')}"
            )
        self._records = {
            record["image_id"]: {
                "image_id": record["image_id"],
                "vector": list(record["vector"]),
                "metadata": copy.deepcopy(record.get("metadata", {})),
            }
            for record in payload.get("records", [])
        }
        if self.index_path.exists():
            loaded_index = self.faiss.read_index(str(self.index_path))
            if loaded_index.d != self.dimension:
                raise VectorDimensionError(
                    f"Expected FAISS index dimension {self.dimension}, got {loaded_index.d}"
                )
            self._image_ids = list(self._records)
            self._index = loaded_index
            return
        self._rebuild_index()

    def _persist(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.faiss.write_index(self._index, str(self.index_path))
        payload = {
            "index_name": self.index_name,
            "dimension": self.dimension,
            "records": [self._records[image_id] for image_id in self._image_ids],
        }
        self.metadata_path.write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

    def _load_dependencies(self) -> tuple[Any, Any]:
        try:
            import faiss
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "FAISS vector index requires faiss-cpu and numpy. "
                "Run `python -m pip install -r requirements.txt`."
            ) from exc
        return faiss, np


def create_vector_index_from_env(
    *,
    dimension: int,
    index_name: str = DEFAULT_INDEX_NAME,
) -> VectorIndexService | RedisVectorIndexService | FAISSVectorIndexService:
    """Create the configured vector index.

    Set IMAGE_RETRIEVAL_VECTOR_INDEX to memory, redis, or faiss.
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
    if backend == "faiss":
        return FAISSVectorIndexService(
            dimension=dimension,
            index_name=index_name,
            index_path=os.getenv("IMAGE_RETRIEVAL_FAISS_INDEX_PATH", DEFAULT_FAISS_INDEX_PATH),
            metadata_path=os.getenv(
                "IMAGE_RETRIEVAL_FAISS_METADATA_PATH",
                DEFAULT_FAISS_METADATA_PATH,
            ),
        )
    return VectorIndexService(dimension=dimension, index_name=index_name)
