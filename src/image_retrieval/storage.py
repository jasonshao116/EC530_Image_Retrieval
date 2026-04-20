"""Document-style storage for images and annotations."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
