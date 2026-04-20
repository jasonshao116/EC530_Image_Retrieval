from __future__ import annotations

import copy
import unittest

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.events import EventValidationError, validate_event
from image_retrieval.pipeline import ImageRetrievalPipeline


IMAGE = {
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
}


def uploaded_event() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "event_id": "11111111-1111-4111-8111-111111111111",
        "event_name": "image.uploaded",
        "event_version": "1.0.0",
        "occurred_at": "2026-04-14T20:00:00Z",
        "source": "push11-test",
        "trace_id": "trace-push11",
        "payload": {"image": copy.deepcopy(IMAGE)},
    }


class IdempotencyTests(unittest.TestCase):
    def test_duplicate_uploaded_event_is_accepted_without_repeating_side_effects(self) -> None:
        pipeline = ImageRetrievalPipeline(source="push11-test")
        event = uploaded_event()

        first = pipeline.process_event(event)
        second = pipeline.process_event(event)

        self.assertEqual(first["status"], "accepted")
        self.assertEqual(len(first["emitted_events"]), 1)
        self.assertEqual(first["emitted_events"][0]["event_name"], "image.indexed")
        self.assertEqual(second["status"], "duplicate")
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["emitted_events"], [])
        self.assertEqual(pipeline.index.image_count, 1)
        self.assertEqual(len(pipeline.events), 2)

    def test_malformed_event_returns_structured_error(self) -> None:
        pipeline = ImageRetrievalPipeline(source="push11-test")

        result = pipeline.process_event({"event_name": "image.uploaded", "payload": {}})

        self.assertEqual(result["status"], "malformed")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"]["error_code"], "malformed_event")
        self.assertIn("message", result["error"])
        self.assertEqual(pipeline.index.image_count, 0)
        self.assertEqual(pipeline.events, [])

    def test_non_object_event_is_reported_as_malformed(self) -> None:
        pipeline = ImageRetrievalPipeline(source="push11-test")

        result = pipeline.process_event(["not", "an", "event"])

        self.assertEqual(result["status"], "malformed")
        self.assertEqual(result["error"]["error_code"], "malformed_event")
        self.assertIn("expected object", result["error"]["message"])

    def test_validate_event_exposes_structured_error_details(self) -> None:
        with self.assertRaises(EventValidationError) as context:
            validate_event(["not", "an", "event"])  # type: ignore[arg-type]

        self.assertEqual(context.exception.as_dict()["error_code"], "malformed_event")


class EventIngestionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ImageRetrievalPipeline(source="push11-api")
        self.client = TestClient(create_app(self.pipeline))

    def test_event_ingestion_endpoint_is_idempotent(self) -> None:
        event = uploaded_event()

        first_response = self.client.post("/events", json=event)
        second_response = self.client.post("/events", json=event)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["status"], "accepted")
        self.assertEqual(first_response.json()["emitted_events"][0]["event_name"], "image.indexed")
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["status"], "duplicate")
        self.assertEqual(self.pipeline.index.image_count, 1)
        self.assertEqual(len(self.pipeline.events), 2)

    def test_event_ingestion_endpoint_rejects_malformed_events(self) -> None:
        response = self.client.post("/events", json={"event_name": "image.uploaded", "payload": {}})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["error_code"], "malformed_event")
        self.assertEqual(self.pipeline.events, [])


if __name__ == "__main__":
    unittest.main()
