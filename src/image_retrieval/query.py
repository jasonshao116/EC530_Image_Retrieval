"""Query service for retrieval requests and CLI workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .events import validate_event
from .pipeline import ImageRetrievalPipeline


class QueryService:
    """High-level query service used by Push 10."""

    def __init__(self, pipeline: ImageRetrievalPipeline | None = None) -> None:
        self.pipeline = pipeline or ImageRetrievalPipeline(source="query-service")

    def index_images(
        self,
        images: list[dict[str, Any]],
        *,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        indexed_events = []
        for image in images:
            upload_event = self.pipeline.upload_image(image, trace_id=trace_id)
            indexed_events.append(self.pipeline.index_uploaded_image(upload_event))
        return indexed_events

    def query_text(
        self,
        query_text: str,
        *,
        top_k: int = 3,
        requested_by: str = "student@example.edu",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if not query_text.strip():
            raise ValueError("query_text must not be empty")
        request_event = self.pipeline.request_retrieval(
            query_text,
            top_k=top_k,
            requested_by=requested_by,
            trace_id=trace_id,
        )
        completed_event = self.pipeline.complete_retrieval(request_event)
        return {
            "query": query_text,
            "request_event": request_event,
            "completed_event": completed_event,
            "results": completed_event["payload"]["results"],
        }

    def query_image(
        self,
        image: dict[str, Any],
        *,
        top_k: int = 3,
        requested_by: str = "student@example.edu",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if "storage_uri" not in image:
            raise ValueError("image query must include storage_uri")
        query_text = self.pipeline.index.searchable_text(image)
        request_event = self.pipeline.request_image_retrieval(
            image["storage_uri"],
            top_k=top_k,
            requested_by=requested_by,
            trace_id=trace_id,
        )
        completed_event = self.pipeline.complete_retrieval(
            request_event,
            exclude_image_id=image.get("image_id"),
            query_override=query_text,
        )
        return {
            "query": image["storage_uri"],
            "request_event": request_event,
            "completed_event": completed_event,
            "results": completed_event["payload"]["results"],
        }


def load_images(path: Path | str) -> list[dict[str, Any]]:
    raw_value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw_value, dict) and isinstance(raw_value.get("images"), list):
        images = raw_value["images"]
    elif isinstance(raw_value, list):
        images = raw_value
    else:
        raise ValueError("image input must be a JSON array or an object with an images array")

    for image in images:
        validate_event(
            {
                "schema_version": "1.0.0",
                "event_id": "00000000-0000-4000-8000-000000000000",
                "event_name": "image.uploaded",
                "event_version": "1.0.0",
                "occurred_at": "2026-04-14T20:00:00Z",
                "source": "query-loader",
                "payload": {"image": image},
            }
        )
    return images
