"""Document-style storage for images and annotations."""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis

from .config import load_dotenv


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DocumentNotFoundError(KeyError):
    """Raised when an image document is not present in storage."""


class ImageDocumentStore:
    """Small JSON-document store used by Push 7.

    The default store is in-memory for tests and local demos. Passing a
    ``path`` makes it file-backed while keeping the same document API.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._documents: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            raw_documents = json.loads(self.path.read_text(encoding="utf-8"))
            self._documents = {document["image_id"]: document for document in raw_documents}

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def upsert_image(self, image: dict[str, Any]) -> dict[str, Any]:
        image_id = image["image_id"]
        existing = self._documents.get(image_id, {})
        now = _now()
        document = {
            "image_id": image_id,
            "image": copy.deepcopy(image),
            "index": existing.get("index"),
            "annotations": existing.get("annotations", []),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        self._documents[image_id] = document
        self._save()
        return copy.deepcopy(document)

    def mark_indexed(self, image_id: str, index_metadata: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document(image_id)
        document["index"] = copy.deepcopy(index_metadata)
        document["updated_at"] = _now()
        self._save()
        return copy.deepcopy(document)

    def get_image(self, image_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require_document(image_id))

    def list_images(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(document) for document in sorted(self._documents.values(), key=lambda item: item["image_id"])]

    def add_annotation(
        self,
        image_id: str,
        annotation: dict[str, Any],
    ) -> dict[str, Any]:
        document = self._require_document(image_id)
        now = _now()
        stored_annotation = {
            "annotation_id": annotation.get("annotation_id", str(uuid.uuid4())),
            "image_id": image_id,
            "label": annotation["label"],
            "annotator": annotation["annotator"],
            "created_at": now,
        }
        if annotation.get("confidence") is not None:
            stored_annotation["confidence"] = annotation["confidence"]
        if annotation.get("notes"):
            stored_annotation["notes"] = annotation["notes"]
        if annotation.get("metadata"):
            stored_annotation["metadata"] = copy.deepcopy(annotation["metadata"])

        document["annotations"].append(stored_annotation)
        document["updated_at"] = now
        self._save()
        return copy.deepcopy(stored_annotation)

    def list_annotations(self, image_id: str) -> list[dict[str, Any]]:
        document = self._require_document(image_id)
        return [copy.deepcopy(annotation) for annotation in document["annotations"]]

    def _require_document(self, image_id: str) -> dict[str, Any]:
        try:
            return self._documents[image_id]
        except KeyError as exc:
            raise DocumentNotFoundError(f"Image document not found: {image_id}") from exc

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.list_images(), indent=2), encoding="utf-8")


class RedisImageDocumentStore:
    """Redis-backed image document store.

    Documents are stored as compact JSON values and tracked in a Redis set so
    the API can list all known image documents.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        namespace: str = "image-retrieval",
        client: Any | None = None,
    ) -> None:
        self.client = client or redis.Redis.from_url(redis_url, decode_responses=True)
        self.namespace = namespace.strip(":")
        self.image_ids_key = f"{self.namespace}:image_ids"

    @property
    def document_count(self) -> int:
        return int(self.client.scard(self.image_ids_key))

    def upsert_image(self, image: dict[str, Any]) -> dict[str, Any]:
        image_id = image["image_id"]
        existing = self._get_document(image_id) or {}
        now = _now()
        document = {
            "image_id": image_id,
            "image": copy.deepcopy(image),
            "index": existing.get("index"),
            "annotations": existing.get("annotations", []),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        self._save_document(document)
        return copy.deepcopy(document)

    def mark_indexed(self, image_id: str, index_metadata: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document(image_id)
        document["index"] = copy.deepcopy(index_metadata)
        document["updated_at"] = _now()
        self._save_document(document)
        return copy.deepcopy(document)

    def get_image(self, image_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require_document(image_id))

    def list_images(self) -> list[dict[str, Any]]:
        image_ids = sorted(self.client.smembers(self.image_ids_key))
        documents = [self._get_document(image_id) for image_id in image_ids]
        return [copy.deepcopy(document) for document in documents if document is not None]

    def add_annotation(
        self,
        image_id: str,
        annotation: dict[str, Any],
    ) -> dict[str, Any]:
        document = self._require_document(image_id)
        now = _now()
        stored_annotation = {
            "annotation_id": annotation.get("annotation_id", str(uuid.uuid4())),
            "image_id": image_id,
            "label": annotation["label"],
            "annotator": annotation["annotator"],
            "created_at": now,
        }
        if annotation.get("confidence") is not None:
            stored_annotation["confidence"] = annotation["confidence"]
        if annotation.get("notes"):
            stored_annotation["notes"] = annotation["notes"]
        if annotation.get("metadata"):
            stored_annotation["metadata"] = copy.deepcopy(annotation["metadata"])

        document["annotations"].append(stored_annotation)
        document["updated_at"] = now
        self._save_document(document)
        return copy.deepcopy(stored_annotation)

    def list_annotations(self, image_id: str) -> list[dict[str, Any]]:
        document = self._require_document(image_id)
        return [copy.deepcopy(annotation) for annotation in document["annotations"]]

    def _document_key(self, image_id: str) -> str:
        return f"{self.namespace}:images:{image_id}"

    def _get_document(self, image_id: str) -> dict[str, Any] | None:
        raw_document = self.client.get(self._document_key(image_id))
        if raw_document is None:
            return None
        return json.loads(raw_document)

    def _require_document(self, image_id: str) -> dict[str, Any]:
        document = self._get_document(image_id)
        if document is None:
            raise DocumentNotFoundError(f"Image document not found: {image_id}")
        return document

    def _save_document(self, document: dict[str, Any]) -> None:
        image_id = document["image_id"]
        self.client.set(
            self._document_key(image_id),
            json.dumps(document, separators=(",", ":"), sort_keys=True),
        )
        self.client.sadd(self.image_ids_key, image_id)


class MongoImageDocumentStore:
    """MongoDB-backed image document store.

    Image documents live in one collection, while image IDs are mirrored into a
    second collection to preserve the existing image ID set behavior.
    """

    def __init__(
        self,
        mongo_uri: str,
        *,
        database_name: str = "image_retrieval",
        image_collection: str = "images",
        image_ids_collection: str = "image_ids",
        client: Any | None = None,
    ) -> None:
        if client is None:
            from pymongo import MongoClient

            client = MongoClient(mongo_uri)
        self.client = client
        self.database_name = database_name
        self.image_collection_name = image_collection
        self.image_ids_collection_name = image_ids_collection
        database = self.client[database_name]
        self.images = database[image_collection]
        self.image_ids = database[image_ids_collection]

    @property
    def document_count(self) -> int:
        return int(self.image_ids.count_documents({}))

    def upsert_image(self, image: dict[str, Any]) -> dict[str, Any]:
        image_id = image["image_id"]
        existing = self._get_document(image_id) or {}
        now = _now()
        document = {
            "image_id": image_id,
            "image": copy.deepcopy(image),
            "index": existing.get("index"),
            "annotations": existing.get("annotations", []),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        self._save_document(document)
        return copy.deepcopy(document)

    def mark_indexed(self, image_id: str, index_metadata: dict[str, Any]) -> dict[str, Any]:
        document = self._require_document(image_id)
        document["index"] = copy.deepcopy(index_metadata)
        document["updated_at"] = _now()
        self._save_document(document)
        return copy.deepcopy(document)

    def get_image(self, image_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require_document(image_id))

    def list_images(self) -> list[dict[str, Any]]:
        documents = list(self.images.find({}, {"_id": False}).sort("image_id", 1))
        return [copy.deepcopy(document) for document in documents]

    def add_annotation(
        self,
        image_id: str,
        annotation: dict[str, Any],
    ) -> dict[str, Any]:
        document = self._require_document(image_id)
        now = _now()
        stored_annotation = {
            "annotation_id": annotation.get("annotation_id", str(uuid.uuid4())),
            "image_id": image_id,
            "label": annotation["label"],
            "annotator": annotation["annotator"],
            "created_at": now,
        }
        if annotation.get("confidence") is not None:
            stored_annotation["confidence"] = annotation["confidence"]
        if annotation.get("notes"):
            stored_annotation["notes"] = annotation["notes"]
        if annotation.get("metadata"):
            stored_annotation["metadata"] = copy.deepcopy(annotation["metadata"])

        document["annotations"].append(stored_annotation)
        document["updated_at"] = now
        self._save_document(document)
        return copy.deepcopy(stored_annotation)

    def list_annotations(self, image_id: str) -> list[dict[str, Any]]:
        document = self._require_document(image_id)
        return [copy.deepcopy(annotation) for annotation in document["annotations"]]

    def _get_document(self, image_id: str) -> dict[str, Any] | None:
        return self.images.find_one({"image_id": image_id}, {"_id": False})

    def _require_document(self, image_id: str) -> dict[str, Any]:
        document = self._get_document(image_id)
        if document is None:
            raise DocumentNotFoundError(f"Image document not found: {image_id}")
        return document

    def _save_document(self, document: dict[str, Any]) -> None:
        image_id = document["image_id"]
        self.images.replace_one({"image_id": image_id}, copy.deepcopy(document), upsert=True)
        self.image_ids.replace_one({"image_id": image_id}, {"image_id": image_id}, upsert=True)


def create_document_store_from_env() -> ImageDocumentStore | RedisImageDocumentStore | MongoImageDocumentStore:
    """Create the configured document store.

    Set IMAGE_RETRIEVAL_DOCUMENT_STORE=mongo and MONGODB_URI to use MongoDB.
    """

    load_dotenv()
    store_backend = os.getenv("IMAGE_RETRIEVAL_DOCUMENT_STORE", "memory").strip().lower()
    if store_backend == "mongo":
        mongo_uri = os.getenv("MONGODB_URI")
        if not mongo_uri:
            raise RuntimeError("MONGODB_URI is required when IMAGE_RETRIEVAL_DOCUMENT_STORE=mongo")
        return MongoImageDocumentStore(
            mongo_uri,
            database_name=os.getenv("MONGODB_DATABASE", "image_retrieval"),
            image_collection=os.getenv("MONGODB_IMAGE_COLLECTION", "images"),
            image_ids_collection=os.getenv("MONGODB_IMAGE_IDS_COLLECTION", "image_ids"),
        )
    if store_backend == "redis":
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise RuntimeError("REDIS_URL is required when IMAGE_RETRIEVAL_DOCUMENT_STORE=redis")
        namespace = os.getenv("REDIS_NAMESPACE", "image-retrieval")
        return RedisImageDocumentStore(redis_url, namespace=namespace)

    document_store_path = os.getenv("IMAGE_RETRIEVAL_DOCUMENT_STORE_PATH")
    if document_store_path:
        return ImageDocumentStore(document_store_path)
    return ImageDocumentStore()
