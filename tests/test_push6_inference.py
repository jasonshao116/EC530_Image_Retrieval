from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.events import validate_event
from image_retrieval.pipeline import ImageRetrievalPipeline


EXISTING_IMAGE = {
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
}

QUERY_IMAGE = {
    "image_id": "f3726f40-6bb5-40b8-8eb0-c43c744d4f73",
    "storage_uri": "s3://ec530-images/uploads/new-campus-building.jpg",
    "content_type": "image/jpeg",
    "width": 1800,
    "height": 1200,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "outdoor"],
}


class UploadInferenceFlowTests(unittest.TestCase):
    def test_pipeline_upload_and_infer_emits_valid_event_flow(self) -> None:
        pipeline = ImageRetrievalPipeline(source="test-inference")
        existing_upload = pipeline.upload_image(EXISTING_IMAGE, trace_id="trace-push6-test")
        pipeline.index_uploaded_image(existing_upload)

        result = pipeline.upload_and_infer(
            QUERY_IMAGE,
            top_k=2,
            requested_by="student@example.edu",
            trace_id="trace-push6-test",
        )

        self.assertEqual(
            [event["event_name"] for event in result.values()],
            [
                "image.uploaded",
                "image.indexed",
                "retrieval.requested",
                "retrieval.completed",
            ],
        )
        for event in result.values():
            validate_event(event)
            self.assertEqual(event["trace_id"], "trace-push6-test")

        request_payload = result["request_event"]["payload"]
        self.assertEqual(request_payload["query_type"], "image")
        self.assertEqual(request_payload["query_image_uri"], QUERY_IMAGE["storage_uri"])

        completed_payload = result["completed_event"]["payload"]
        self.assertEqual(completed_payload["result_count"], 1)
        self.assertEqual(completed_payload["results"][0]["image_id"], EXISTING_IMAGE["image_id"])
        self.assertNotEqual(completed_payload["results"][0]["image_id"], QUERY_IMAGE["image_id"])

    def test_api_upload_and_infer_endpoint(self) -> None:
        pipeline = ImageRetrievalPipeline(source="test-api")
        client = TestClient(create_app(pipeline))

        upload_response = client.post("/images", json={**EXISTING_IMAGE, "trace_id": "trace-api-push6"})
        self.assertEqual(upload_response.status_code, 200)

        inference_response = client.post(
            "/inferences",
            json={
                **QUERY_IMAGE,
                "top_k": 2,
                "requested_by": "student@example.edu",
                "trace_id": "trace-api-push6",
            },
        )
        self.assertEqual(inference_response.status_code, 200)

        body = inference_response.json()
        self.assertEqual(body["image_id"], QUERY_IMAGE["image_id"])
        validate_event(body["upload_event"])
        validate_event(body["indexed_event"])
        validate_event(body["request_event"])
        validate_event(body["completed_event"])
        self.assertEqual(body["request_event"]["payload"]["query_type"], "image")
        self.assertEqual(body["completed_event"]["payload"]["result_count"], 1)
        self.assertEqual(
            body["completed_event"]["payload"]["results"][0]["image_id"],
            EXISTING_IMAGE["image_id"],
        )


if __name__ == "__main__":
    unittest.main()
