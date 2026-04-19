"""Synthetic event generator for Push 5."""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any, Literal, TextIO

from .events import validate_event
from .pipeline import ImageRetrievalPipeline


EventOutputFormat = Literal["json", "jsonl"]


_IMAGE_THEMES = [
    {
        "name": "campus-quad",
        "tags": ["campus", "outdoor", "brick", "building"],
        "content_type": "image/jpeg",
        "width": 1920,
        "height": 1080,
    },
    {
        "name": "library-study",
        "tags": ["library", "indoor", "books", "study"],
        "content_type": "image/jpeg",
        "width": 1600,
        "height": 1067,
    },
    {
        "name": "river-bridge",
        "tags": ["river", "outdoor", "bridge", "water"],
        "content_type": "image/png",
        "width": 2048,
        "height": 1365,
    },
    {
        "name": "lab-equipment",
        "tags": ["lab", "indoor", "equipment", "research"],
        "content_type": "image/jpeg",
        "width": 1280,
        "height": 960,
    },
    {
        "name": "street-night",
        "tags": ["street", "night", "lights", "city"],
        "content_type": "image/jpeg",
        "width": 1440,
        "height": 960,
    },
]

_QUERY_TEMPLATES = [
    "brick campus building",
    "quiet indoor library books",
    "outdoor bridge over river",
    "research lab equipment",
    "city street lights at night",
]


class EventGenerator:
    """Create schema-valid event streams by driving the retrieval pipeline."""

    def __init__(
        self,
        *,
        seed: int | None = None,
        source: str = "push5-event-generator",
        uploaded_by: str = "student@example.edu",
        requested_by: str = "student@example.edu",
    ) -> None:
        self._random = random.Random(seed)
        self.source = source
        self.uploaded_by = uploaded_by
        self.requested_by = requested_by

    def generate(
        self,
        *,
        image_count: int = 3,
        retrieval_count: int = 2,
        top_k: int = 3,
        trace_id: str | None = "trace-push5-generator",
    ) -> list[dict[str, Any]]:
        """Generate upload/index/retrieval event pairs for demos and tests."""

        if image_count < 1:
            raise ValueError("image_count must be at least 1")
        if retrieval_count < 0:
            raise ValueError("retrieval_count must be zero or greater")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        pipeline = ImageRetrievalPipeline(source=self.source)

        for index in range(image_count):
            image = self._image(index)
            upload_event = pipeline.upload_image(image, trace_id=trace_id)
            pipeline.index_uploaded_image(upload_event)

        for _ in range(retrieval_count):
            query_text = self._query()
            request_event = pipeline.request_retrieval(
                query_text,
                top_k=top_k,
                requested_by=self.requested_by,
                trace_id=trace_id,
            )
            pipeline.complete_retrieval(request_event)

        return [validate_event(event) for event in pipeline.events]

    def _image(self, index: int) -> dict[str, Any]:
        theme = self._random.choice(_IMAGE_THEMES)
        image_uuid = uuid.UUID(int=self._random.getrandbits(128), version=4)
        extension = "png" if theme["content_type"] == "image/png" else "jpg"
        tags = list(theme["tags"])
        self._random.shuffle(tags)
        return {
            "image_id": str(image_uuid),
            "storage_uri": f"s3://ec530-images/generated/{theme['name']}-{index + 1:03d}.{extension}",
            "content_type": theme["content_type"],
            "width": theme["width"],
            "height": theme["height"],
            "uploaded_by": self.uploaded_by,
            "tags": tags,
        }

    def _query(self) -> str:
        return self._random.choice(_QUERY_TEMPLATES)


def generate_event_stream(
    *,
    image_count: int = 3,
    retrieval_count: int = 2,
    top_k: int = 3,
    seed: int | None = None,
    source: str = "push5-event-generator",
    trace_id: str | None = "trace-push5-generator",
) -> list[dict[str, Any]]:
    """Convenience wrapper for creating a complete synthetic event stream."""

    return EventGenerator(seed=seed, source=source).generate(
        image_count=image_count,
        retrieval_count=retrieval_count,
        top_k=top_k,
        trace_id=trace_id,
    )


def write_events(
    events: list[dict[str, Any]],
    output: Path | TextIO,
    *,
    output_format: EventOutputFormat = "json",
) -> None:
    """Write events as a JSON array or newline-delimited JSON."""

    if output_format not in {"json", "jsonl"}:
        raise ValueError("output_format must be 'json' or 'jsonl'")

    should_close = False
    if isinstance(output, Path):
        stream = output.open("w", encoding="utf-8")
        should_close = True
    else:
        stream = output

    try:
        if output_format == "json":
            json.dump(events, stream, indent=2)
            stream.write("\n")
        else:
            for event in events:
                stream.write(json.dumps(event, separators=(",", ":")))
                stream.write("\n")
    finally:
        if should_close:
            stream.close()
