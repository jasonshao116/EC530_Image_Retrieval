"""FastAPI application for Push 4."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .events import EventValidationError
from .pipeline import ImageRetrievalPipeline


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
