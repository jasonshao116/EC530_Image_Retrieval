from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.events import validate_event
from image_retrieval.pipeline import ImageRetrievalPipeline


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ImageRetrievalPipeline(source="test-api")
        self.client = TestClient(create_app(self.pipeline))

    def test_health_reports_empty_pipeline(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "indexed_images": 0, "stored_images": 0, "event_count": 0},
        )

    def test_upload_and_retrieve_images(self) -> None:
        upload_response = self.client.post(
            "/images",
            json={
                "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
                "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
                "content_type": "image/jpeg",
                "width": 1920,
                "height": 1080,
                "uploaded_by": "student@example.edu",
                "tags": ["campus", "brick", "building"],
                "trace_id": "trace-api-test",
            },
        )
        self.assertEqual(upload_response.status_code, 200)

        upload_body = upload_response.json()
        validate_event(upload_body["upload_event"])
        validate_event(upload_body["indexed_event"])
        self.assertEqual(upload_body["indexed_event"]["trace_id"], "trace-api-test")

        retrieval_response = self.client.post(
            "/retrievals",
            json={
                "query_text": "brick campus building",
                "top_k": 1,
                "requested_by": "student@example.edu",
                "trace_id": "trace-api-test",
            },
        )
        self.assertEqual(retrieval_response.status_code, 200)

        retrieval_body = retrieval_response.json()
        validate_event(retrieval_body["request_event"])
        validate_event(retrieval_body["completed_event"])
        self.assertEqual(retrieval_body["completed_event"]["payload"]["result_count"], 1)
        self.assertEqual(
            retrieval_body["completed_event"]["payload"]["results"][0]["image_id"],
            "80253575-f761-4a68-a20f-75a66dcf0c88",
        )

    def test_invalid_image_payload_is_rejected(self) -> None:
        response = self.client.post(
            "/images",
            json={
                "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
                "storage_uri": "s3://ec530-images/dataset/campus-001.txt",
                "content_type": "text/plain",
                "width": 1920,
                "height": 1080,
                "uploaded_by": "student@example.edu",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_web_upload_page_is_available(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("EC530 Image Retrieval", response.text)
        self.assertIn('type="file"', response.text)
        self.assertIn("function matchCard(result)", response.text)
        self.assertIn("const cards = body.images.map(imageCard);", response.text)
        self.assertNotIn("body.images.map((document)", response.text)

    def test_upload_file_indexes_image_from_multipart_form(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = ImageRetrievalPipeline(source="test-web-upload")
            client = TestClient(create_app(pipeline, upload_dir=Path(temp_dir)))
            client.post(
                "/images",
                json={
                    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
                    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
                    "content_type": "image/jpeg",
                    "width": 1920,
                    "height": 1080,
                    "uploaded_by": "student@example.edu",
                    "tags": ["campus", "brick", "building"],
                },
            )

            response = client.post(
                "/uploads",
                data={
                    "tags": "campus, upload",
                    "uploaded_by": "student@example.edu",
                    "top_k": "2",
                },
                files={"file": ("query.png", ONE_PIXEL_PNG, "image/png")},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            validate_event(body["upload_event"])
            validate_event(body["indexed_event"])
            validate_event(body["request_event"])
            validate_event(body["completed_event"])
            image = body["upload_event"]["payload"]["image"]
            self.assertEqual(image["content_type"], "image/png")
            self.assertEqual(image["width"], 1)
            self.assertEqual(image["height"], 1)
            self.assertEqual(image["tags"], ["campus", "upload"])
            self.assertTrue((Path(temp_dir) / Path(image["storage_uri"]).name).exists())
            self.assertEqual(body["completed_event"]["payload"]["result_count"], 1)


if __name__ == "__main__":
    unittest.main()
