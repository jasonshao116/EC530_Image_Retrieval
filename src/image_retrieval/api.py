"""FastAPI application for Push 4."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .events import EventValidationError
from .pipeline import ImageRetrievalPipeline
from .storage import DocumentNotFoundError


class ImageMetadataRequest(BaseModel):
    image_id: str
    storage_uri: str = Field(min_length=1)
    content_type: str = Field(pattern=r"^image/")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    uploaded_by: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    trace_id: str | None = Field(default=None, min_length=1)


class RetrievalRequest(BaseModel):
    query_text: str = Field(min_length=1)
    top_k: int = Field(default=3, gt=0)
    requested_by: str = Field(default="student@example.edu", min_length=1)
    trace_id: str | None = Field(default=None, min_length=1)


class UploadInferenceRequest(ImageMetadataRequest):
    top_k: int = Field(default=3, gt=0)
    requested_by: str = Field(default="student@example.edu", min_length=1)


class AnnotationRequest(BaseModel):
    label: str = Field(min_length=1)
    annotator: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(pipeline: ImageRetrievalPipeline | None = None) -> FastAPI:
    app = FastAPI(
        title="EC530 Image Retrieval API",
        version="1.0.0",
        description="REST API for the event-driven image retrieval pipeline.",
    )
    app.state.pipeline = pipeline or ImageRetrievalPipeline(source="push4-api")

    @app.get("/health")
    def health() -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        return {
            "status": "ok",
            "indexed_images": current_pipeline.index.image_count,
            "stored_images": current_pipeline.document_store.document_count,
            "event_count": len(current_pipeline.events),
        }

    @app.post("/images")
    def upload_image(request: ImageMetadataRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        image = request.model_dump(exclude={"trace_id"})
        try:
            upload_event = current_pipeline.upload_image(image, trace_id=request.trace_id)
            indexed_event = current_pipeline.index_uploaded_image(upload_event)
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "image_id": image["image_id"],
            "upload_event": upload_event,
            "indexed_event": indexed_event,
        }

    @app.get("/images")
    def list_images() -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        images = current_pipeline.document_store.list_images()
        return {
            "image_count": len(images),
            "images": images,
        }

    @app.get("/images/{image_id}")
    def get_image(image_id: str) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            return current_pipeline.document_store.get_image(image_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/images/{image_id}/annotations")
    def add_annotation(image_id: str, request: AnnotationRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            annotation = current_pipeline.document_store.add_annotation(
                image_id,
                request.model_dump(exclude_none=True),
            )
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return annotation

    @app.get("/images/{image_id}/annotations")
    def list_annotations(image_id: str) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            annotations = current_pipeline.document_store.list_annotations(image_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "image_id": image_id,
            "annotation_count": len(annotations),
            "annotations": annotations,
        }

    @app.post("/retrievals")
    def retrieve(request: RetrievalRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            requested_event = current_pipeline.request_retrieval(
                request.query_text,
                top_k=request.top_k,
                requested_by=request.requested_by,
                trace_id=request.trace_id,
            )
            completed_event = current_pipeline.complete_retrieval(requested_event)
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "request_event": requested_event,
            "completed_event": completed_event,
        }

    @app.post("/inferences")
    def upload_and_infer(request: UploadInferenceRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        image = request.model_dump(exclude={"trace_id", "top_k", "requested_by"})
        try:
            result = current_pipeline.upload_and_infer(
                image,
                top_k=request.top_k,
                requested_by=request.requested_by,
                trace_id=request.trace_id,
            )
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "image_id": image["image_id"],
            **result,
        }

    @app.get("/events")
    def list_events() -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        return {
            "event_count": len(current_pipeline.events),
            "events": current_pipeline.events,
        }

    return app


app = create_app()
