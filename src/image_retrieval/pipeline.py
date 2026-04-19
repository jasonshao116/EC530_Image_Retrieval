"""Small event-driven image retrieval pipeline for Push 3."""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from .events import validate_event


DEFAULT_EMBEDDING_DIMENSION = 16
DEFAULT_INDEX_NAME = "image-embeddings-v1"
DEFAULT_MODEL = "hash-token-embedding-v1"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event(
    event_name: str,
    source: str,
    payload: dict[str, Any],
    trace_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "schema_version": "1.0.0",
        "event_id": str(uuid.uuid4()),
        "event_name": event_name,
        "event_version": "1.0.0",
        "occurred_at": _now(),
        "source": source,
        "payload": payload,
    }
    if trace_id:
        event["trace_id"] = trace_id
    return validate_event(event)


def _tokens(value: str) -> list[str]:
    return [
        token.strip().lower()
        for token in value.replace("/", " ").replace("-", " ").replace("_", " ").split()
        if token.strip()
    ]


def _embed_text(value: str, dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    for token in _tokens(value):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % dimension
        sign = 1 if digest[2] % 2 == 0 else -1
        vector[bucket] += sign
    return vector


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class InMemoryImageIndex:
    """Deterministic local index used for the Push 3 demo and tests."""

    def __init__(self, embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> None:
        self.embedding_dimension = embedding_dimension
        self._images: dict[str, dict[str, Any]] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, image: dict[str, Any]) -> None:
        image_id = image["image_id"]
        searchable_text = " ".join(
            [
                image.get("storage_uri", ""),
                image.get("content_type", ""),
                " ".join(image.get("tags", [])),
            ]
        )
        self._images[image_id] = image
        self._vectors[image_id] = _embed_text(searchable_text, self.embedding_dimension)

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        query_vector = _embed_text(query, self.embedding_dimension)
        scored_matches = [
            (image_id, _cosine_similarity(query_vector, image_vector))
            for image_id, image_vector in self._vectors.items()
        ]
        scored_matches.sort(key=lambda match: match[1], reverse=True)

        results = []
        for rank, (image_id, score) in enumerate(scored_matches[:top_k], start=1):
            image = self._images[image_id]
            results.append(
                {
                    "image_id": image_id,
                    "score": round(score, 4),
                    "rank": rank,
                    "storage_uri": image["storage_uri"],
                }
            )
        return results


class ImageRetrievalPipeline:
    """Consumes schema-valid events and emits downstream retrieval events."""

    def __init__(self, index: InMemoryImageIndex | None = None) -> None:
        self.index = index or InMemoryImageIndex()
        self.events: list[dict[str, Any]] = []

    def upload_image(
        self,
        image: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        event = _event("image.uploaded", "push3-demo", {"image": image}, trace_id)
        self.events.append(event)
        return event

    def index_uploaded_image(self, upload_event: dict[str, Any]) -> dict[str, Any]:
        upload_event = validate_event(upload_event)
        image = upload_event["payload"]["image"]
        self.index.add(image)

        event = _event(
            "image.indexed",
            "push3-demo",
            {
                "image_id": image["image_id"],
                "index_name": DEFAULT_INDEX_NAME,
                "embedding_model": DEFAULT_MODEL,
                "embedding_dimension": self.index.embedding_dimension,
                "indexed_at": _now(),
            },
            upload_event.get("trace_id"),
        )
        self.events.append(event)
        return event

    def request_retrieval(
        self,
        query_text: str,
        *,
        top_k: int = 3,
        requested_by: str = "student@example.edu",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        event = _event(
            "retrieval.requested",
            "push3-demo",
            {
                "request_id": str(uuid.uuid4()),
                "query_type": "text",
                "query_text": query_text,
                "top_k": top_k,
                "requested_by": requested_by,
            },
            trace_id,
        )
        self.events.append(event)
        return event

    def complete_retrieval(self, request_event: dict[str, Any]) -> dict[str, Any]:
        request_event = validate_event(request_event)
        payload = request_event["payload"]
        started_at = datetime.now(UTC)
        results = self.index.search(payload["query_text"], payload["top_k"])
        latency_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)

        event = _event(
            "retrieval.completed",
            "push3-demo",
            {
                "request_id": payload["request_id"],
                "latency_ms": latency_ms,
                "result_count": len(results),
                "results": results,
            },
            request_event.get("trace_id"),
        )
        self.events.append(event)
        return event
