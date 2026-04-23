"""FastAPI application for Push 4."""

from __future__ import annotations

import os
import struct
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .events import EventValidationError
from .failure import FailureInjectionError
from .pipeline import ImageRetrievalPipeline
from .storage import DocumentNotFoundError, create_document_store_from_env
from .vector_index import VectorDimensionError


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


class EmbeddingTextRequest(BaseModel):
    text: str = Field(min_length=1)


class EmbeddingImageRequest(BaseModel):
    image: ImageMetadataRequest


class VectorUpsertRequest(BaseModel):
    image_id: str
    vector: list[float] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorSearchRequest(BaseModel):
    vector: list[float] = Field(min_length=1)
    top_k: int = Field(default=3, gt=0)
    exclude_image_id: str | None = Field(default=None, min_length=1)


def _safe_filename(filename: str) -> str:
    stem = Path(filename).stem or "upload"
    suffix = Path(filename).suffix.lower()
    safe_stem = "".join(character if character.isalnum() else "-" for character in stem).strip("-")
    return f"{safe_stem or 'upload'}{suffix}"


def _image_dimensions(content: bytes) -> tuple[int, int]:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width, height = struct.unpack(">II", content[16:24])
        return width, height

    if content[:6] in {b"GIF87a", b"GIF89a"} and len(content) >= 10:
        width, height = struct.unpack("<HH", content[6:10])
        return width, height

    if content.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(content):
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                break
            marker = content[offset]
            offset += 1
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(content):
                break
            segment_length = struct.unpack(">H", content[offset : offset + 2])[0]
            if segment_length < 2 or offset + segment_length > len(content):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                if offset + 7 > len(content):
                    break
                height, width = struct.unpack(">HH", content[offset + 3 : offset + 7])
                return width, height
            offset += segment_length

    raise ValueError("Could not determine image dimensions. Try a PNG, GIF, or JPEG file.")


def _upload_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EC530 Image Retrieval</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #18202b;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; }
    main {
      width: min(1080px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 40px 0;
      display: grid;
      gap: 24px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 20px;
      border-bottom: 1px solid #d9dee7;
      padding-bottom: 18px;
    }
    h1 { margin: 0; font-size: clamp(2rem, 6vw, 4.8rem); line-height: .95; letter-spacing: 0; }
    header p { max-width: 420px; margin: 0; color: #556071; line-height: 1.5; }
    .workspace {
      display: grid;
      grid-template-columns: minmax(280px, 380px) minmax(0, 1fr);
      gap: 24px;
      align-items: start;
    }
    form, .results, .library {
      background: #ffffff;
      border: 1px solid #dfe4ec;
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 14px 34px rgba(30, 42, 58, .08);
    }
    label { display: grid; gap: 8px; font-weight: 700; font-size: .92rem; color: #273245; }
    input, button {
      width: 100%;
      border-radius: 6px;
      border: 1px solid #c8d0dc;
      font: inherit;
      min-height: 44px;
    }
    input { padding: 10px 12px; background: #fbfcfe; }
    input[type="file"] { padding: 8px; }
    button {
      border: 0;
      background: #0f766e;
      color: #fff;
      font-weight: 800;
      cursor: pointer;
    }
    button:disabled { background: #8aa3a0; cursor: wait; }
    .fields { display: grid; gap: 14px; }
    .preview {
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: contain;
      background: #eef2f6;
      border: 1px dashed #aab5c4;
      border-radius: 8px;
    }
    .status { min-height: 22px; color: #445266; }
    .event-list, .match-list { display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }
    .event-list li, .match-list li {
      border: 1px solid #e1e6ee;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
      overflow-wrap: anywhere;
    }
    .event-name { font-weight: 800; color: #0f766e; }
    .score { color: #5d6878; font-size: .9rem; }
    .match-card {
      display: grid;
      grid-template-columns: 112px minmax(0, 1fr);
      gap: 14px;
      align-items: center;
    }
    .match-card img {
      width: 112px;
      aspect-ratio: 1;
      object-fit: cover;
      border-radius: 6px;
      background: #eef2f6;
      border: 1px solid #e1e6ee;
    }
    .match-meta { display: grid; gap: 4px; min-width: 0; }
    .match-title { font-weight: 800; color: #1f2937; overflow-wrap: anywhere; }
    .library-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
    }
    .thumb {
      display: grid;
      gap: 8px;
      border: 1px solid #e1e6ee;
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfe;
      min-width: 0;
    }
    .thumb img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px; background: #eef2f6; }
    .thumb span { font-size: .82rem; overflow-wrap: anywhere; color: #445266; }
    @media (max-width: 760px) {
      main { padding: 24px 0; }
      header, .workspace { grid-template-columns: 1fr; display: grid; }
      header { align-items: start; }
      .match-card { grid-template-columns: 84px minmax(0, 1fr); }
      .match-card img { width: 84px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>EC530 Image Retrieval</h1>
      <p>Upload an image from your laptop, index it through the pipeline, and see the emitted events.</p>
    </header>
    <section class="workspace">
      <form id="upload-form">
        <div class="fields">
          <label>Image file
            <input id="image-file" name="file" type="file" accept="image/*" required>
          </label>
          <img class="preview" id="preview" alt="">
          <label>Tags
            <input name="tags" placeholder="campus, brick, outdoor">
          </label>
          <label>Uploaded by
            <input name="uploaded_by" value="student@example.edu" required>
          </label>
          <label>Top K
            <input name="top_k" type="number" min="1" value="3" required>
          </label>
          <input id="image-width" name="width" type="hidden">
          <input id="image-height" name="height" type="hidden">
          <button id="submit-button" type="submit">Upload Image</button>
          <div class="status" id="status"></div>
        </div>
      </form>
      <section class="results">
        <h2>Pipeline Output</h2>
        <ul class="event-list" id="events"></ul>
        <h2>Matches</h2>
        <ul class="match-list" id="matches"></ul>
      </section>
    </section>
    <section class="library">
      <h2>Uploaded Images</h2>
      <div class="library-grid" id="library"></div>
    </section>
  </main>
  <script>
    const form = document.querySelector("#upload-form");
    const fileInput = document.querySelector("#image-file");
    const preview = document.querySelector("#preview");
    const statusBox = document.querySelector("#status");
    const events = document.querySelector("#events");
    const matches = document.querySelector("#matches");
    const library = document.querySelector("#library");
    const button = document.querySelector("#submit-button");
    const imageWidth = document.querySelector("#image-width");
    const imageHeight = document.querySelector("#image-height");

    function item(text, className) {
      const li = document.createElement("li");
      if (className) li.className = className;
      li.textContent = text;
      return li;
    }

    function imageCard(imageDocument) {
      const card = document.createElement("div");
      card.className = "thumb";
      const image = document.createElement("img");
      image.src = imageDocument.image.storage_uri;
      image.alt = imageDocument.image.image_id;
      image.loading = "lazy";
      const label = document.createElement("span");
      label.textContent = imageDocument.image.tags?.join(", ") || imageDocument.image.image_id;
      card.append(image, label);
      return card;
    }

    function matchCard(result) {
      const li = document.createElement("li");
      li.className = "match-card";
      const image = document.createElement("img");
      image.src = result.storage_uri;
      image.alt = result.image_id;
      image.loading = "lazy";
      const meta = document.createElement("div");
      meta.className = "match-meta";
      const title = document.createElement("div");
      title.className = "match-title";
      title.textContent = "#" + result.rank + " " + result.image_id;
      const score = document.createElement("div");
      score.className = "score";
      score.textContent = "score " + result.score.toFixed(4);
      meta.append(title, score);
      li.append(image, meta);
      return li;
    }

    function renderUpload(body) {
      events.replaceChildren(
        item(body.upload_event.event_name + " | " + body.upload_event.event_id, "event-name"),
        item(body.indexed_event.event_name + " | " + body.indexed_event.event_id, "event-name"),
        item(body.request_event.event_name + " | " + body.request_event.event_id, "event-name"),
        item(body.completed_event.event_name + " | " + body.completed_event.event_id, "event-name"),
      );
      const results = body.completed_event.payload.results || [];
      matches.replaceChildren(...(results.length ? results.map(matchCard) : [item("No other indexed images yet.")]));
    }

    async function refreshLibrary() {
      const response = await fetch("/images");
      const body = await response.json();
      const cards = body.images.map(imageCard);
      library.replaceChildren(...(cards.length ? cards : [item("No uploads yet.")]));
    }

    fileInput.addEventListener("change", () => {
      const file = fileInput.files[0];
      preview.removeAttribute("src");
      imageWidth.value = "";
      imageHeight.value = "";
      preview.onload = () => {
        imageWidth.value = preview.naturalWidth || "";
        imageHeight.value = preview.naturalHeight || "";
      };
      if (file) preview.src = URL.createObjectURL(file);
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      button.disabled = true;
      statusBox.textContent = "Uploading...";
      try {
        const response = await fetch("/uploads", { method: "POST", body: formData });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Upload failed");
        statusBox.textContent = "Uploaded " + body.image_id;
        renderUpload(body);
        await refreshLibrary();
      } catch (error) {
        statusBox.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });

    refreshLibrary();
  </script>
</body>
</html>"""


def create_app(
    pipeline: ImageRetrievalPipeline | None = None,
    upload_dir: Path | str | None = None,
) -> FastAPI:
    configured_pipeline = pipeline or ImageRetrievalPipeline(
        source="push4-api",
        document_store=create_document_store_from_env(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        current_pipeline.reindex_stored_images()
        yield

    app = FastAPI(
        title="EC530 Image Retrieval API",
        version="1.0.0",
        description="REST API for the event-driven image retrieval pipeline.",
        lifespan=lifespan,
    )
    app.state.pipeline = configured_pipeline
    configured_upload_dir = upload_dir or os.getenv("IMAGE_RETRIEVAL_UPLOAD_DIR", "data/uploads")
    app.state.upload_dir = Path(configured_upload_dir)
    app.state.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploaded-files", StaticFiles(directory=app.state.upload_dir), name="uploaded-files")

    def injected_failure_response(exc: FailureInjectionError) -> HTTPException:
        return HTTPException(
            status_code=503,
            detail={
                "error_code": "injected_failure",
                "failure_point": exc.failure_point,
                "message": str(exc),
            },
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        return {
            "status": "ok",
            "indexed_images": current_pipeline.index.image_count,
            "stored_images": current_pipeline.document_store.document_count,
            "event_count": len(current_pipeline.events),
        }

    @app.get("/", response_class=HTMLResponse)
    def web_upload_form() -> HTMLResponse:
        return HTMLResponse(_upload_page())

    @app.post("/uploads")
    async def upload_file(
        file: UploadFile = File(...),
        tags: str = Form(default=""),
        uploaded_by: str = Form(default="student@example.edu"),
        top_k: int = Form(default=3, gt=0),
        width: int | None = Form(default=None),
        height: int | None = Form(default=None),
    ) -> dict[str, Any]:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="Upload must be an image file.")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Upload must not be empty.")

        if not width or not height or width < 1 or height < 1:
            try:
                width, height = _image_dimensions(content)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        image_id = str(uuid.uuid4())
        safe_name = _safe_filename(file.filename or "upload")
        stored_name = f"{image_id}-{safe_name}"
        destination = app.state.upload_dir / stored_name
        destination.write_bytes(content)

        image = {
            "image_id": image_id,
            "storage_uri": f"/uploaded-files/{quote(stored_name)}",
            "content_type": file.content_type,
            "width": width,
            "height": height,
            "uploaded_by": uploaded_by,
            "tags": [tag.strip() for tag in tags.split(",") if tag.strip()],
        }

        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        trace_id = f"web-upload-{image_id}"
        try:
            result = current_pipeline.upload_and_infer(
                image,
                top_k=top_k,
                requested_by=uploaded_by,
                trace_id=trace_id,
            )
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FailureInjectionError as exc:
            raise injected_failure_response(exc) from exc

        return {
            "image_id": image_id,
            "file_url": image["storage_uri"],
            **result,
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
        except FailureInjectionError as exc:
            raise injected_failure_response(exc) from exc

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

    @app.post("/embeddings/text")
    def embed_text(request: EmbeddingTextRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        return current_pipeline.index.embedding_service.embed_text(request.text).as_dict()

    @app.post("/embeddings/image")
    def embed_image(request: EmbeddingImageRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        image = request.image.model_dump(exclude={"trace_id"})
        return current_pipeline.index.embedding_service.embed_image(image).as_dict()

    @app.get("/vector-index")
    def vector_index_stats() -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        return current_pipeline.index.vector_index.stats()

    @app.post("/vector-index")
    def upsert_vector(request: VectorUpsertRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            return current_pipeline.index.vector_index.upsert(
                request.image_id,
                request.vector,
                metadata=request.metadata,
            )
        except VectorDimensionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/vector-index/search")
    def search_vectors(request: VectorSearchRequest) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        try:
            results = current_pipeline.index.vector_index.search(
                request.vector,
                request.top_k,
                exclude_image_id=request.exclude_image_id,
            )
        except VectorDimensionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "result_count": len(results),
            "results": results,
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
        except FailureInjectionError as exc:
            raise injected_failure_response(exc) from exc

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
        except FailureInjectionError as exc:
            raise injected_failure_response(exc) from exc

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

    @app.post("/events")
    def ingest_event(event: Any = Body(...)) -> dict[str, Any]:
        current_pipeline: ImageRetrievalPipeline = app.state.pipeline
        result = current_pipeline.process_event(event)
        if result["status"] == "malformed":
            raise HTTPException(status_code=422, detail=result["error"])
        if result["status"] == "failed":
            raise HTTPException(status_code=503, detail=result["error"])
        return result

    return app


app = create_app()
