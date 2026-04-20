"""Small event-driven image retrieval pipeline."""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from .events import validate_event
from .storage import ImageDocumentStore


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
    """Deterministic local index used for the demo, API, and tests."""

    def __init__(self, embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> None:
        self.embedding_dimension = embedding_dimension
        self._images: dict[str, dict[str, Any]] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, image: dict[str, Any]) -> None:
        image_id = image["image_id"]
        searchable_text = self.searchable_text(image)
        self._images[image_id] = image
        self._vectors[image_id] = _embed_text(searchable_text, self.embedding_dimension)

    @property
    def image_count(self) -> int:
        return len(self._images)

    def searchable_text(self, image: dict[str, Any]) -> str:
        return " ".join(
            [
                image.get("storage_uri", ""),
                image.get("content_type", ""),
                " ".join(image.get("tags", [])),
            ]
        )

    def search(
        self,
        query: str,
        top_k: int,
        *,
        exclude_image_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_vector(
            _embed_text(query, self.embedding_dimension),
            top_k,
            exclude_image_id=exclude_image_id,
        )

    def search_vector(
        self,
        query_vector: list[float],
        top_k: int,
        *,
        exclude_image_id: str | None = None,
    ) -> list[dict[str, Any]]:
        scored_matches = [
            (image_id, _cosine_similarity(query_vector, image_vector))
            for image_id, image_vector in self._vectors.items()
            if image_id != exclude_image_id
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

    def __init__(
        self,
        index: InMemoryImageIndex | None = None,
        source: str = "image-retrieval-service",
        document_store: ImageDocumentStore | None = None,
    ) -> None:
        self.index = index or InMemoryImageIndex()
        self.source = source
        self.document_store = document_store or ImageDocumentStore()
        self.events: list[dict[str, Any]] = []

    def upload_image(
        self,
        image: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        event = _event("image.uploaded", self.source, {"image": image}, trace_id)
        self.document_store.upsert_image(image)
        self.events.append(event)
        return event

    def index_uploaded_image(self, upload_event: dict[str, Any]) -> dict[str, Any]:
        upload_event = validate_event(upload_event)
        image = upload_event["payload"]["image"]
        self.index.add(image)
        index_metadata = {
            "index_name": DEFAULT_INDEX_NAME,
            "embedding_model": DEFAULT_MODEL,
            "embedding_dimension": self.index.embedding_dimension,
            "indexed_at": _now(),
        }

        event = _event(
            "image.indexed",
            self.source,
            {
                "image_id": image["image_id"],
                **index_metadata,
            },
            upload_event.get("trace_id"),
        )
        self.document_store.mark_indexed(image["image_id"], index_metadata)
        self.events.append(event)
        return event

    def upload_and_infer(
        self,
        image: dict[str, Any],
        *,
        top_k: int = 3,
        requested_by: str = "student@example.edu",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        upload_event = self.upload_image(image, trace_id=trace_id)
        indexed_event = self.index_uploaded_image(upload_event)
        request_event = self.request_image_retrieval(
            image["storage_uri"],
            top_k=top_k,
            requested_by=requested_by,
            trace_id=trace_id,
        )
        completed_event = self.complete_retrieval(
            request_event,
            exclude_image_id=image["image_id"],
            query_override=self.index.searchable_text(image),
        )
        return {
            "upload_event": upload_event,
            "indexed_event": indexed_event,
            "request_event": request_event,
            "completed_event": completed_event,
        }

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
            self.source,
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

    def request_image_retrieval(
        self,
        query_image_uri: str,
        *,
        top_k: int = 3,
        requested_by: str = "student@example.edu",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        event = _event(
            "retrieval.requested",
            self.source,
            {
                "request_id": str(uuid.uuid4()),
                "query_type": "image",
                "query_image_uri": query_image_uri,
                "top_k": top_k,
                "requested_by": requested_by,
            },
            trace_id,
        )
        self.events.append(event)
        return event

    def complete_retrieval(
        self,
        request_event: dict[str, Any],
        *,
        exclude_image_id: str | None = None,
        query_override: str | None = None,
    ) -> dict[str, Any]:
        request_event = validate_event(request_event)
        payload = request_event["payload"]
        started_at = datetime.now(UTC)
        query = query_override or payload.get("query_text") or payload["query_image_uri"]
        results = self.index.search(query, payload["top_k"], exclude_image_id=exclude_image_id)
        latency_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)

        event = _event(
            "retrieval.completed",
            self.source,
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
