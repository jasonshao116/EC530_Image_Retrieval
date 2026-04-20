from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.pipeline import ImageRetrievalPipeline
from image_retrieval.storage import ImageDocumentStore


IMAGE = {
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
}


class DocumentStorageTests(unittest.TestCase):
    def test_pipeline_persists_image_document_and_index_metadata(self) -> None:
        store = ImageDocumentStore()
        pipeline = ImageRetrievalPipeline(source="test-storage", document_store=store)

        upload_event = pipeline.upload_image(IMAGE, trace_id="trace-push7")
        pipeline.index_uploaded_image(upload_event)

        document = store.get_image(IMAGE["image_id"])
        self.assertEqual(document["image"], IMAGE)
        self.assertIsNotNone(document["index"])
        self.assertEqual(document["index"]["index_name"], "image-embeddings-v1")
        self.assertEqual(document["annotations"], [])

    def test_file_backed_store_round_trips_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "documents.json"
            store = ImageDocumentStore(path)
            store.upsert_image(IMAGE)
            store.add_annotation(
                IMAGE["image_id"],
                {
                    "label": "campus-building",
                    "annotator": "reviewer@example.edu",
                    "confidence": 0.95,
                    "metadata": {"split": "train"},
                },
            )

            reloaded_store = ImageDocumentStore(path)
            document = reloaded_store.get_image(IMAGE["image_id"])
            self.assertEqual(document["image"]["storage_uri"], IMAGE["storage_uri"])
            self.assertEqual(document["annotations"][0]["label"], "campus-building")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[0]["image_id"], IMAGE["image_id"])


class AnnotationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ImageRetrievalPipeline(source="test-api")
        self.client = TestClient(create_app(self.pipeline))

    def test_image_documents_and_annotations_are_available_through_api(self) -> None:
        upload_response = self.client.post("/images", json={**IMAGE, "trace_id": "trace-push7-api"})
        self.assertEqual(upload_response.status_code, 200)

        list_response = self.client.get("/images")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["image_count"], 1)
        self.assertEqual(list_response.json()["images"][0]["image_id"], IMAGE["image_id"])

        image_response = self.client.get(f"/images/{IMAGE['image_id']}")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.json()["index"]["embedding_model"], "hash-token-embedding-v1")

        annotation_response = self.client.post(
            f"/images/{IMAGE['image_id']}/annotations",
            json={
                "label": "campus-building",
                "annotator": "reviewer@example.edu",
                "confidence": 0.9,
                "notes": "Brick academic building.",
                "metadata": {"source": "manual-review"},
            },
        )
        self.assertEqual(annotation_response.status_code, 200)
        self.assertEqual(annotation_response.json()["label"], "campus-building")

        annotations_response = self.client.get(f"/images/{IMAGE['image_id']}/annotations")
        self.assertEqual(annotations_response.status_code, 200)
        self.assertEqual(annotations_response.json()["annotation_count"], 1)
        self.assertEqual(annotations_response.json()["annotations"][0]["annotator"], "reviewer@example.edu")

    def test_annotation_for_missing_image_returns_404(self) -> None:
        response = self.client.post(
            "/images/00000000-0000-4000-8000-000000000000/annotations",
            json={"label": "missing", "annotator": "reviewer@example.edu"},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
