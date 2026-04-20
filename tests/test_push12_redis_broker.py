from __future__ import annotations

import copy
import unittest

from image_retrieval.broker import InMemoryEventBroker
from image_retrieval.events import EventValidationError
from image_retrieval.pipeline import ImageRetrievalPipeline
from image_retrieval.worker import process_and_publish


IMAGE_UPLOADED_EVENT = {
    "schema_version": "1.0.0",
    "event_id": "22222222-2222-4222-8222-222222222222",
    "event_name": "image.uploaded",
    "event_version": "1.0.0",
    "occurred_at": "2026-04-14T20:00:00Z",
    "source": "redis-broker-test",
    "trace_id": "trace-redis",
    "payload": {
        "image": {
            "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
            "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
            "content_type": "image/jpeg",
            "width": 1920,
            "height": 1080,
            "uploaded_by": "student@example.edu",
            "tags": ["campus", "brick", "building"],
        }
    },
}


class BrokerTests(unittest.TestCase):
    def test_in_memory_broker_routes_by_event_name(self) -> None:
        broker = InMemoryEventBroker()

        broker.publish(copy.deepcopy(IMAGE_UPLOADED_EVENT))
        events = list(broker.listen(["image.uploaded"]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_name"], "image.uploaded")
        self.assertEqual(events[0]["event_id"], IMAGE_UPLOADED_EVENT["event_id"])

    def test_in_memory_broker_validates_before_publish(self) -> None:
        broker = InMemoryEventBroker()
        bad_event = copy.deepcopy(IMAGE_UPLOADED_EVENT)
        bad_event["event_id"] = "not-a-uuid"

        with self.assertRaises(EventValidationError):
            broker.publish(bad_event)

    def test_worker_processes_and_publishes_downstream_events(self) -> None:
        broker = InMemoryEventBroker()
        pipeline = ImageRetrievalPipeline(source="redis-worker-test")

        result = process_and_publish(
            copy.deepcopy(IMAGE_UPLOADED_EVENT),
            pipeline=pipeline,
            broker=broker,
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["emitted_events"][0]["event_name"], "image.indexed")
        self.assertEqual(broker.published_events[0]["event_name"], "image.indexed")
        self.assertEqual(pipeline.index.image_count, 1)


if __name__ == "__main__":
    unittest.main()
