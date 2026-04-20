from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from image_retrieval.query import QueryService, load_images


IMAGES = [
    {
        "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
        "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
        "content_type": "image/jpeg",
        "width": 1920,
        "height": 1080,
        "uploaded_by": "student@example.edu",
        "tags": ["campus", "brick", "building"],
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
]


class QueryServiceTests(unittest.TestCase):
    def test_query_service_indexes_images_and_returns_ranked_results(self) -> None:
        service = QueryService()
        indexed_events = service.index_images(IMAGES, trace_id="trace-push10")

        result = service.query_text("brick campus", top_k=1, trace_id="trace-push10")

        self.assertEqual(len(indexed_events), 2)
        self.assertEqual(result["completed_event"]["payload"]["result_count"], 1)
        self.assertEqual(result["results"][0]["image_id"], IMAGES[0]["image_id"])
        self.assertEqual(result["request_event"]["trace_id"], "trace-push10")

    def test_query_service_rejects_empty_text_query(self) -> None:
        service = QueryService()

        with self.assertRaises(ValueError):
            service.query_text("   ")

    def test_load_images_accepts_array_or_images_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            array_path = Path(temp_dir) / "images-array.json"
            object_path = Path(temp_dir) / "images-object.json"
            array_path.write_text(json.dumps(IMAGES), encoding="utf-8")
            object_path.write_text(json.dumps({"images": IMAGES}), encoding="utf-8")

            self.assertEqual(load_images(array_path), IMAGES)
            self.assertEqual(load_images(object_path), IMAGES)


class QueryCliTests(unittest.TestCase):
    def test_query_cli_outputs_json_results_from_image_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            images_path = Path(temp_dir) / "images.json"
            images_path.write_text(json.dumps(IMAGES), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "image_retrieval.demo",
                    "query",
                    "brick campus",
                    "--images",
                    str(images_path),
                    "--top-k",
                    "1",
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        body = json.loads(completed.stdout)
        self.assertEqual(body["query"], "brick campus")
        self.assertEqual(body["completed_event"]["payload"]["result_count"], 1)
        self.assertEqual(body["results"][0]["image_id"], IMAGES[0]["image_id"])


if __name__ == "__main__":
    unittest.main()
