"""Command line tools for the image retrieval pushes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .events import EventValidationError, load_event, load_schema, validate_event
from .generator import generate_event_stream, write_events
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


def run_infer_demo(top_k: int) -> int:
    pipeline = ImageRetrievalPipeline()
    trace_id = "trace-push6-inference-demo"

    for image in _sample_images()[:2]:
        upload_event = pipeline.upload_image(image, trace_id=trace_id)
        pipeline.index_uploaded_image(upload_event)

    result = pipeline.upload_and_infer(
        {
            "image_id": "f3726f40-6bb5-40b8-8eb0-c43c744d4f73",
            "storage_uri": "s3://ec530-images/uploads/new-campus-building.jpg",
            "content_type": "image/jpeg",
            "width": 1800,
            "height": 1200,
            "uploaded_by": "student@example.edu",
            "tags": ["campus", "brick", "outdoor"],
        },
        top_k=top_k,
        trace_id=trace_id,
    )
    print(json.dumps(result, indent=2))
    return 0


def generate_command(
    *,
    image_count: int,
    retrieval_count: int,
    top_k: int,
    seed: int | None,
    output_format: str,
    output_path: Path | None,
) -> int:
    events = generate_event_stream(
        image_count=image_count,
        retrieval_count=retrieval_count,
        top_k=top_k,
        seed=seed,
    )
    output = output_path if output_path else sys.stdout
    write_events(events, output, output_format=output_format)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Image retrieval event tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate event JSON files")
    validate_parser.add_argument("paths", nargs="+", type=Path)

    demo_parser = subparsers.add_parser("demo", help="run a local retrieval demo")
    demo_parser.add_argument("--query", default="red brick campus building")
    demo_parser.add_argument("--top-k", type=int, default=3)

    infer_parser = subparsers.add_parser("infer", help="run the Push 6 upload + inference flow")
    infer_parser.add_argument("--top-k", type=int, default=3)

    generate_parser = subparsers.add_parser("generate", help="generate Push 5 synthetic events")
    generate_parser.add_argument("--images", type=int, default=3, help="number of uploaded images to generate")
    generate_parser.add_argument("--retrievals", type=int, default=2, help="number of retrieval requests to generate")
    generate_parser.add_argument("--top-k", type=int, default=3)
    generate_parser.add_argument("--seed", type=int, default=None, help="seed for repeatable generated images and queries")
    generate_parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    generate_parser.add_argument("--output", type=Path, default=None, help="write generated events to a file")

    args = parser.parse_args()
    try:
        if args.command == "validate":
            return validate_command(args.paths)
        if args.command == "demo":
            return run_demo(args.query, args.top_k)
        if args.command == "infer":
            return run_infer_demo(args.top_k)
        if args.command == "generate":
            return generate_command(
                image_count=args.images,
                retrieval_count=args.retrievals,
                top_k=args.top_k,
                seed=args.seed,
                output_format=args.format,
                output_path=args.output,
            )
    except (EventValidationError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
