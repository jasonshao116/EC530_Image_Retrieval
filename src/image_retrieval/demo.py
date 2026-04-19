"""Command line demo for Push 3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .events import EventValidationError, load_event, load_schema, validate_event
from .pipeline import ImageRetrievalPipeline


def _sample_images() -> list[dict[str, object]]:
    return [
        {
            "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
            "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
            "content_type": "image/jpeg",
            "width": 1920,
            "height": 1080,
            "uploaded_by": "student@example.edu",
            "tags": ["campus", "outdoor", "building", "brick"],
        },
        {
            "image_id": "b06fb9f8-49e0-46bb-94d3-cce55c4ba38a",
            "storage_uri": "s3://ec530-images/dataset/library-014.jpg",
            "content_type": "image/jpeg",
            "width": 1600,
            "height": 1067,
            "uploaded_by": "student@example.edu",
            "tags": ["library", "indoor", "books"],
        },
        {
            "image_id": "cfe9bd53-50bf-4f8d-8d78-99ca030c8801",
            "storage_uri": "s3://ec530-images/dataset/river-112.jpg",
            "content_type": "image/jpeg",
            "width": 2048,
            "height": 1365,
            "uploaded_by": "student@example.edu",
            "tags": ["river", "outdoor", "bridge"],
        },
    ]


def validate_command(paths: list[Path]) -> int:
    schema = load_schema()
    for path in paths:
        validate_event(load_event(path), schema)
        print(f"valid: {path}")
    return 0


def run_demo(query: str, top_k: int) -> int:
    pipeline = ImageRetrievalPipeline()
    trace_id = "trace-push3-demo"

    for image in _sample_images():
        upload_event = pipeline.upload_image(image, trace_id=trace_id)
        pipeline.index_uploaded_image(upload_event)

    request_event = pipeline.request_retrieval(query, top_k=top_k, trace_id=trace_id)
    completed_event = pipeline.complete_retrieval(request_event)
    print(json.dumps(completed_event, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Push 3 image retrieval tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate event JSON files")
    validate_parser.add_argument("paths", nargs="+", type=Path)

    demo_parser = subparsers.add_parser("demo", help="run a local retrieval demo")
    demo_parser.add_argument("--query", default="red brick campus building")
    demo_parser.add_argument("--top-k", type=int, default=3)

    args = parser.parse_args()
    try:
        if args.command == "validate":
            return validate_command(args.paths)
        if args.command == "demo":
            return run_demo(args.query, args.top_k)
    except EventValidationError as exc:
        parser.exit(1, f"{exc}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
