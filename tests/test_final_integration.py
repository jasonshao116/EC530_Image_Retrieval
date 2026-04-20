from __future__ import annotations

import copy
import subprocess
import sys
import unittest

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.failure import FailureInjector
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
        "event_id": "22222222-2222-4222-8222-222222222222",
        "event_name": "image.uploaded",
        "event_version": "1.0.0",
        "occurred_at": "2026-04-14T20:00:00Z",
        "source": "final-integration-test",
        "trace_id": "trace-final",
        "payload": {"image": copy.deepcopy(IMAGE)},
    }


def retrieval_event() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "event_id": "33333333-3333-4333-8333-333333333333",
        "event_name": "retrieval.requested",
        "event_version": "1.0.0",
        "occurred_at": "2026-04-14T20:01:00Z",
        "source": "final-integration-test",
        "trace_id": "trace-final",
        "payload": {
            "request_id": "44444444-4444-4444-8444-444444444444",
            "query_type": "text",
            "query_text": "brick campus",
            "top_k": 1,
            "requested_by": "student@example.edu",
        },
    }


class FinalIntegrationTests(unittest.TestCase):
    def test_ingested_upload_then_retrieval_flow_end_to_end(self) -> None:
        pipeline = ImageRetrievalPipeline(source="final-integration")

        upload_result = pipeline.process_event(uploaded_event())
        retrieval_result = pipeline.process_event(retrieval_event())

        self.assertEqual(upload_result["status"], "accepted")
        self.assertEqual(upload_result["emitted_events"][0]["event_name"], "image.indexed")
        self.assertEqual(retrieval_result["status"], "accepted")
        completed_event = retrieval_result["emitted_events"][0]
        self.assertEqual(completed_event["event_name"], "retrieval.completed")
        self.assertEqual(completed_event["payload"]["result_count"], 1)
        self.assertEqual(completed_event["payload"]["results"][0]["image_id"], IMAGE["image_id"])
        self.assertEqual(pipeline.index.image_count, 1)

    def test_injected_ingestion_failure_can_be_retried_after_clearing_failure(self) -> None:
        injector = FailureInjector({"before_process_image.uploaded"})
        pipeline = ImageRetrievalPipeline(source="final-integration", failure_injector=injector)
        event = uploaded_event()

        failed = pipeline.process_event(event)
        injector.clear()
        retried = pipeline.process_event(event)
        duplicate = pipeline.process_event(event)

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["error_code"], "injected_failure")
        self.assertEqual(pipeline.index.image_count, 1)
        self.assertEqual(retried["status"], "accepted")
        self.assertEqual(duplicate["status"], "duplicate")

    def test_api_reports_injected_failures_as_503(self) -> None:
        injector = FailureInjector({"before_complete_retrieval"})
        pipeline = ImageRetrievalPipeline(source="final-integration-api", failure_injector=injector)
        client = TestClient(create_app(pipeline))

        upload_response = client.post("/images", json=IMAGE)
        retrieval_response = client.post(
            "/retrievals",
            json={"query_text": "brick campus", "top_k": 1},
        )

        self.assertEqual(upload_response.status_code, 200)
        self.assertEqual(retrieval_response.status_code, 503)
        self.assertEqual(retrieval_response.json()["detail"]["error_code"], "injected_failure")
        self.assertEqual(retrieval_response.json()["detail"]["failure_point"], "before_complete_retrieval")

    def test_cli_query_integration_smoke_test(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "image_retrieval.demo",
                "query",
                "brick campus",
                "--top-k",
                "1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("rank\tscore\timage_id\tstorage_uri", completed.stdout)
        self.assertIn(IMAGE["image_id"], completed.stdout)


if __name__ == "__main__":
    unittest.main()
