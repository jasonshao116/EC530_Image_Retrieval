from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from image_retrieval.api import create_app
from image_retrieval.embedding import EmbeddingService
from image_retrieval.pipeline import ImageRetrievalPipeline
from image_retrieval.vector_index import RedisVectorIndexService, VectorDimensionError, VectorIndexService


IMAGE = {
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
}


class FakeRedisHashClient:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def hlen(self, key: str) -> int:
        return len(self.hashes.get(key, {}))

    def hdel(self, key: str, field: str) -> int:
        existed = field in self.hashes.get(key, {})
        self.hashes.get(key, {}).pop(field, None)
        return int(existed)


class EmbeddingServiceTests(unittest.TestCase):
    def test_text_embeddings_are_repeatable(self) -> None:
        service = EmbeddingService(dimension=8)

        first = service.embed_text("brick campus building")
        second = service.embed_text("brick campus building")

        self.assertEqual(first.vector, second.vector)
        self.assertEqual(first.dimension, 8)
        self.assertEqual(first.model, "hash-token-embedding-v1")

    def test_image_embedding_uses_searchable_image_metadata(self) -> None:
        service = EmbeddingService(dimension=8)

        image_embedding = service.embed_image(IMAGE)
        text_embedding = service.embed_text(
            "s3://ec530-images/dataset/campus-001.jpg image/jpeg campus brick building"
        )

        self.assertEqual(image_embedding.vector, text_embedding.vector)


class VectorIndexServiceTests(unittest.TestCase):
    def test_vector_index_ranks_by_cosine_similarity(self) -> None:
        index = VectorIndexService(dimension=3)
        index.upsert("image-a", [1.0, 0.0, 0.0], metadata={"storage_uri": "s3://a.jpg"})
        index.upsert("image-b", [0.0, 1.0, 0.0], metadata={"storage_uri": "s3://b.jpg"})

        results = index.search([1.0, 0.0, 0.0], top_k=2)

        self.assertEqual(results[0]["image_id"], "image-a")
        self.assertEqual(results[0]["score"], 1.0)
        self.assertEqual(results[0]["rank"], 1)
        self.assertEqual(results[1]["image_id"], "image-b")

    def test_vector_index_rejects_wrong_dimension(self) -> None:
        index = VectorIndexService(dimension=3)

        with self.assertRaises(VectorDimensionError):
            index.upsert("image-a", [1.0, 0.0])

    def test_redis_vector_index_persists_vectors_and_embeddings(self) -> None:
        client = FakeRedisHashClient()
        index = RedisVectorIndexService(
            "redis://example.invalid:6379/0",
            dimension=3,
            namespace="test-vectors",
            client=client,
        )

        index.upsert("image-a", [1.0, 0.0, 0.0], metadata={"storage_uri": "s3://a.jpg"})
        index.upsert("image-b", [0.0, 1.0, 0.0], metadata={"storage_uri": "s3://b.jpg"})
        results = index.search([1.0, 0.0, 0.0], top_k=2)

        self.assertEqual(index.vector_count, 2)
        self.assertEqual(results[0]["image_id"], "image-a")
        self.assertEqual(results[0]["score"], 1.0)
        self.assertIn("image-a", client.hashes["test-vectors:vectors"])
        self.assertIn("image-a", client.hashes["test-vectors:embeddings"])


class EmbeddingAndVectorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ImageRetrievalPipeline(source="test-push8-9")
        self.client = TestClient(create_app(self.pipeline))

    def test_embedding_and_vector_index_endpoints_work_together(self) -> None:
        embedding_response = self.client.post("/embeddings/image", json={"image": IMAGE})
        self.assertEqual(embedding_response.status_code, 200)
        embedding = embedding_response.json()
        self.assertEqual(embedding["dimension"], 16)

        upsert_response = self.client.post(
            "/vector-index",
            json={
                "image_id": IMAGE["image_id"],
                "vector": embedding["vector"],
                "metadata": {"storage_uri": IMAGE["storage_uri"]},
            },
        )
        self.assertEqual(upsert_response.status_code, 200)

        search_response = self.client.post(
            "/vector-index/search",
            json={"vector": embedding["vector"], "top_k": 1},
        )
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(search_response.json()["result_count"], 1)
        self.assertEqual(search_response.json()["results"][0]["image_id"], IMAGE["image_id"])

        stats_response = self.client.get("/vector-index")
        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.json()["vector_count"], 1)

    def test_pipeline_uses_embedding_and_vector_services_for_retrieval(self) -> None:
        upload_event = self.pipeline.upload_image(IMAGE, trace_id="trace-push8-9")
        self.pipeline.index_uploaded_image(upload_event)

        request_event = self.pipeline.request_retrieval("brick campus building", top_k=1)
        completed_event = self.pipeline.complete_retrieval(request_event)

        self.assertEqual(self.pipeline.index.vector_index.vector_count, 1)
        self.assertEqual(completed_event["payload"]["result_count"], 1)
        self.assertEqual(completed_event["payload"]["results"][0]["storage_uri"], IMAGE["storage_uri"])


if __name__ == "__main__":
    unittest.main()
