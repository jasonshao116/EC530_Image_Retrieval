"""Small event-driven image retrieval pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .embedding import DEFAULT_EMBEDDING_DIMENSION, DEFAULT_MODEL, EmbeddingService
from .events import EventValidationError, validate_event
from .failure import FailureInjectionError, FailureInjector
from .storage import ImageDocumentStore
from .vector_index import DEFAULT_INDEX_NAME, RedisVectorIndexService, VectorIndexService


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


class InMemoryImageIndex:
    """Deterministic local index used for the demo, API, and tests."""

    def __init__(
        self,
        embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        *,
        embedding_service: EmbeddingService | None = None,
        vector_index: VectorIndexService | RedisVectorIndexService | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService(dimension=embedding_dimension)
        self.vector_index = vector_index or VectorIndexService(
            dimension=self.embedding_service.dimension,
            index_name=DEFAULT_INDEX_NAME,
        )
        self.embedding_dimension = self.embedding_service.dimension
        self._images: dict[str, dict[str, Any]] = {}

    def add(self, image: dict[str, Any]) -> None:
        image_id = image["image_id"]
        self._images[image_id] = image
        embedding = self.embedding_service.embed_image(image)
        self.vector_index.upsert(
            image_id,
            embedding.vector,
            metadata={
                "storage_uri": image["storage_uri"],
                "content_type": image["content_type"],
                "tags": list(image.get("tags", [])),
            },
        )

    @property
    def image_count(self) -> int:
        return self.vector_index.vector_count

    def searchable_text(self, image: dict[str, Any]) -> str:
        return self.embedding_service.searchable_image_text(image)

    def search(
        self,
        query: str,
        top_k: int,
        *,
        exclude_image_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_vector(
            self.embedding_service.embed_text(query).vector,
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
        matches = self.vector_index.search(
            query_vector,
            top_k,
            exclude_image_id=exclude_image_id,
        )
        return [
            {
                "image_id": match["image_id"],
                "score": match["score"],
                "rank": match["rank"],
                "storage_uri": match["metadata"]["storage_uri"],
            }
            for match in matches
        ]


class ImageRetrievalPipeline:
    """Consumes schema-valid events and emits downstream retrieval events."""

    def __init__(
        self,
        index: InMemoryImageIndex | None = None,
        source: str = "image-retrieval-service",
        document_store: ImageDocumentStore | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self.index = index or InMemoryImageIndex()
        self.source = source
        self.document_store = document_store or ImageDocumentStore()
        self.failure_injector = failure_injector or FailureInjector()
        self.events: list[dict[str, Any]] = []
        self._processed_event_ids: set[str] = set()

    def _inject_failure(self, failure_point: str) -> None:
        self.failure_injector.check(failure_point)

    def upload_image(
        self,
        image: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._inject_failure("before_upload_image")
        event = _event("image.uploaded", self.source, {"image": image}, trace_id)
        self.document_store.upsert_image(image)
        self.events.append(event)
        return event

    def index_uploaded_image(self, upload_event: dict[str, Any]) -> dict[str, Any]:
        self._inject_failure("before_index_image")
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

    def reindex_stored_images(self) -> int:
        """Rebuild the in-memory vector index from persisted image documents."""

        indexed_count = 0
        for document in self.document_store.list_images():
            image = document["image"]
            self.index.add(image)
            indexed_count += 1
        return indexed_count

    def process_event(self, event: Any) -> dict[str, Any]:
        """Validate and process an incoming event idempotently.

        Duplicate event IDs are acknowledged without repeating side effects.
        Malformed events return a structured error object instead of raising.
        """

        try:
            validated_event = validate_event(event)
        except EventValidationError as exc:
            return {
                "status": "malformed",
                "accepted": False,
                "duplicate": False,
                "error": exc.as_dict(),
                "emitted_events": [],
            }

        event_id = validated_event["event_id"]
        if event_id in self._processed_event_ids:
            return {
                "status": "duplicate",
                "accepted": True,
                "duplicate": True,
                "event_id": event_id,
                "event_name": validated_event["event_name"],
                "emitted_events": [],
            }

        event_name = validated_event["event_name"]
        emitted_events: list[dict[str, Any]] = []

        try:
            self._inject_failure(f"before_process_{event_name}")
            if event_name == "image.uploaded":
                self.events.append(validated_event)
                image = validated_event["payload"]["image"]
                self.document_store.upsert_image(image)
                emitted_events.append(self.index_uploaded_image(validated_event))
            elif event_name == "retrieval.requested":
                self.events.append(validated_event)
                emitted_events.append(self.complete_retrieval(validated_event))
            elif event_name in {"image.indexed", "retrieval.completed"}:
                self.events.append(validated_event)
            else:
                return {
                    "status": "malformed",
                    "accepted": False,
                    "duplicate": False,
                    "error": {
                        "error_code": "unsupported_event",
                        "event_name": event_name,
                        "path": "event_name",
                        "message": f"Unsupported event: {event_name}",
                    },
                    "emitted_events": [],
                }
        except FailureInjectionError as exc:
            return {
                "status": "failed",
                "accepted": False,
                "duplicate": False,
                "event_id": event_id,
                "event_name": event_name,
                "error": {
                    "error_code": "injected_failure",
                    "failure_point": exc.failure_point,
                    "message": str(exc),
                },
                "emitted_events": [],
            }

        self._processed_event_ids.add(event_id)
        return {
            "status": "accepted",
            "accepted": True,
            "duplicate": False,
            "event_id": event_id,
            "event_name": event_name,
            "emitted_events": emitted_events,
        }

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
        self._inject_failure("before_request_retrieval")
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
        self._inject_failure("before_request_image_retrieval")
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
        self._inject_failure("before_complete_retrieval")
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
