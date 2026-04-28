from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.pipeline import ImageRetrievalPipeline
from image_retrieval.storage import (
    ImageDocumentStore,
    MongoImageDocumentStore,
    RedisImageDocumentStore,
    create_document_store_from_env,
)


IMAGE = {
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
}


SECOND_IMAGE = {
    "image_id": "f3726f40-6bb5-40b8-8eb0-c43c744d4f73",
    "storage_uri": "s3://ec530-images/uploads/new-campus-building.jpg",
    "content_type": "image/jpeg",
    "width": 1800,
    "height": 1200,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "outdoor"],
}


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))


class FakeMongoCursor:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: int) -> list[dict[str, object]]:
        reverse = direction < 0
        return sorted(self.documents, key=lambda item: item[key], reverse=reverse)


class FakeMongoCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}

    def count_documents(self, query: dict[str, object]) -> int:
        return len(list(self._matching_documents(query)))

    def find_one(self, query: dict[str, object], projection: dict[str, bool] | None = None) -> dict[str, object] | None:
        del projection
        return next(self._matching_documents(query), None)

    def find(self, query: dict[str, object], projection: dict[str, bool] | None = None) -> FakeMongoCursor:
        del projection
        return FakeMongoCursor(list(self._matching_documents(query)))

    def replace_one(self, query: dict[str, object], document: dict[str, object], upsert: bool = False) -> None:
        del upsert
        key = str(query.get("image_id") or document.get("image_id"))
        self.documents[key] = dict(document)

    def _matching_documents(self, query: dict[str, object]):
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in query.items()):
                yield dict(document)


class FakeMongoDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return self.collections.setdefault(name, FakeMongoCollection())


class FakeMongoClient:
    def __init__(self) -> None:
        self.databases: dict[str, FakeMongoDatabase] = {}

    def __getitem__(self, name: str) -> FakeMongoDatabase:
        return self.databases.setdefault(name, FakeMongoDatabase())


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

    def test_redis_store_round_trips_documents(self) -> None:
        client = FakeRedis()
        store = RedisImageDocumentStore(
            "redis://example.invalid:6379/0",
            namespace="test-images",
            client=client,
        )
        store.upsert_image(IMAGE)
        store.mark_indexed(
            IMAGE["image_id"],
            {
                "index_name": "image-embeddings-v1",
                "embedding_model": "hash-token-embedding-v1",
                "embedding_dimension": 16,
                "indexed_at": "2026-04-23T00:00:00Z",
            },
        )
        store.add_annotation(
            IMAGE["image_id"],
            {
                "label": "campus-building",
                "annotator": "reviewer@example.edu",
                "confidence": 0.95,
            },
        )

        document = store.get_image(IMAGE["image_id"])
        self.assertEqual(store.document_count, 1)
        self.assertEqual(document["image"], IMAGE)
        self.assertEqual(document["index"]["index_name"], "image-embeddings-v1")
        self.assertEqual(document["annotations"][0]["label"], "campus-building")
        self.assertEqual(store.list_images()[0]["image_id"], IMAGE["image_id"])

    def test_mongo_store_round_trips_documents_and_image_id_set(self) -> None:
        client = FakeMongoClient()
        store = MongoImageDocumentStore(
            "mongodb://example.invalid:27017",
            database_name="test-db",
            client=client,
        )
        store.upsert_image(IMAGE)
        store.mark_indexed(
            IMAGE["image_id"],
            {
                "index_name": "image-embeddings-v1",
                "embedding_model": "hash-token-embedding-v1",
                "embedding_dimension": 16,
                "indexed_at": "2026-04-23T00:00:00Z",
            },
        )
        store.add_annotation(
            IMAGE["image_id"],
            {
                "label": "campus-building",
                "annotator": "reviewer@example.edu",
                "confidence": 0.95,
            },
        )

        document = store.get_image(IMAGE["image_id"])
        self.assertEqual(store.document_count, 1)
        self.assertEqual(document["image"], IMAGE)
        self.assertEqual(document["index"]["index_name"], "image-embeddings-v1")
        self.assertEqual(document["annotations"][0]["label"], "campus-building")
        self.assertEqual(store.list_images()[0]["image_id"], IMAGE["image_id"])

    def test_store_factory_uses_redis_when_configured(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IMAGE_RETRIEVAL_DOCUMENT_STORE": "redis",
                "REDIS_URL": "rediss://default:secret@example.redis-cloud.com:12345",
                "REDIS_NAMESPACE": "ec530-test",
            },
            clear=False,
        ):
            store = create_document_store_from_env()

        self.assertIsInstance(store, RedisImageDocumentStore)
        self.assertEqual(store.namespace, "ec530-test")

    def test_store_factory_uses_mongo_when_configured(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IMAGE_RETRIEVAL_DOCUMENT_STORE": "mongo",
                "MONGODB_URI": "mongodb://example.invalid:27017",
                "MONGODB_DATABASE": "ec530-test",
            },
            clear=False,
        ):
            with patch("image_retrieval.storage.MongoImageDocumentStore") as store_class:
                create_document_store_from_env()

        store_class.assert_called_once()
        self.assertEqual(store_class.call_args.kwargs["database_name"], "ec530-test")

    def test_pipeline_reindexes_stored_images_for_search_after_restart(self) -> None:
        store = ImageDocumentStore()
        store.upsert_image(IMAGE)
        store.upsert_image(SECOND_IMAGE)
        pipeline = ImageRetrievalPipeline(source="test-reindex", document_store=store)

        self.assertEqual(pipeline.index.image_count, 0)
        indexed_count = pipeline.reindex_stored_images()

        self.assertEqual(indexed_count, 2)
        self.assertEqual(pipeline.index.image_count, 2)
        results = pipeline.index.search("brick campus", top_k=2)
        self.assertEqual(len(results), 2)

    def test_api_reindexes_stored_images_on_startup(self) -> None:
        store = ImageDocumentStore()
        store.upsert_image(IMAGE)
        pipeline = ImageRetrievalPipeline(source="test-api-reindex", document_store=store)

        with TestClient(create_app(pipeline)) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stored_images"], 1)
        self.assertEqual(response.json()["indexed_images"], 1)


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
