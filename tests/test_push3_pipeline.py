from __future__ import annotations

import json
import unittest
from pathlib import Path

from image_retrieval.events import EventValidationError, load_schema, validate_event
from image_retrieval.pipeline import ImageRetrievalPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EventValidationTests(unittest.TestCase):
    def test_examples_match_schema(self) -> None:
        schema = load_schema()
        for event_path in sorted((PROJECT_ROOT / "examples").glob("*.json")):
            with self.subTest(event=event_path.name):
                event = json.loads(event_path.read_text(encoding="utf-8"))
                self.assertIs(validate_event(event, schema), event)

    def test_invalid_event_reports_context(self) -> None:
        bad_event = {
            "schema_version": "1.0.0",
            "event_id": "not-a-uuid",
            "event_name": "image.uploaded",
            "event_version": "1.0.0",
            "occurred_at": "2026-04-14T20:00:00Z",
            "source": "test",
            "payload": {"image": {}},
        }

        with self.assertRaises(EventValidationError):
            validate_event(bad_event)


class PipelineTests(unittest.TestCase):
    def test_pipeline_emits_valid_completed_event(self) -> None:
        pipeline = ImageRetrievalPipeline()
        upload_event = pipeline.upload_image(
            {
                "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
                "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
                "content_type": "image/jpeg",
                "width": 1920,
                "height": 1080,
                "uploaded_by": "student@example.edu",
                "tags": ["campus", "brick", "building"],
            },
            trace_id="trace-test",
        )
        pipeline.index_uploaded_image(upload_event)

        request_event = pipeline.request_retrieval("brick campus building", top_k=1, trace_id="trace-test")
        completed_event = pipeline.complete_retrieval(request_event)

        validate_event(completed_event)
        self.assertEqual(completed_event["event_name"], "retrieval.completed")
        self.assertEqual(completed_event["trace_id"], "trace-test")
        self.assertEqual(completed_event["payload"]["result_count"], 1)
        self.assertEqual(completed_event["payload"]["results"][0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
