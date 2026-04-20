# EC530_Image_Retrieval

This repository contains an event-driven image retrieval prototype. It combines
the Push 2 event schema, the Push 3 executable validation and local retrieval
pipeline, the Push 4 REST API, the Push 5 synthetic event generator, the Push 6
upload plus inference flow, the Push 7 document database with annotation
storage, the Push 8/9 embedding plus vector index services, the Push 10 query
service plus CLI, and Push 11 idempotent event ingestion with malformed-event
handling. The final push adds deterministic failure injection and integration
tests across the ingestion, API, and CLI paths.

The system models four core pipeline stages:

- `image.uploaded`
- `image.indexed`
- `retrieval.requested`
- `retrieval.completed`

Each stage uses a shared event envelope, a strongly typed payload contract, and
schema validation before events are accepted or emitted.

## What It Includes

- Versioned JSON Schema for all supported events
- Sample event JSON files for each pipeline stage
- JSON Schema validation helpers
- Deterministic in-memory image indexing and retrieval
- CLI commands for validation and demo retrieval
- REST API for uploading images, searching images, and inspecting emitted events
- Synthetic event generation for local testing and downstream consumers
- Upload plus inference flow for image-query retrieval
- Document-style image records with optional file-backed persistence
- Annotation storage attached to each image document
- Deterministic embedding service for text and image metadata
- In-memory vector index service with cosine-similarity search
- Query service and CLI command for running ranked searches from sample or JSON image data
- Idempotent event ingestion that ignores duplicate event IDs without repeating side effects
- Structured malformed-event errors for invalid event payloads
- Deterministic failure injection hooks for resilience and integration testing
- Unit tests for the examples and retrieval pipeline

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Run the Project

Run validation, tests, and an API import check:

```bash
make all
```

Validate the sample events:

```bash
make validate
```

Run the local retrieval demo:

```bash
make demo
```

Generate a Push 5 synthetic event stream:

```bash
make generate
```

Run the Push 6 upload plus inference demo:

```bash
make infer
```

Run the Push 10 query service from the CLI:

```bash
make query
```

Or query a JSON file containing an array of image metadata records:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo query \
  "brick campus" \
  --images images.json \
  --top-k 3 \
  --format json
```

Or write newline-delimited JSON for ingestion tools:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo generate \
  --images 5 \
  --retrievals 3 \
  --top-k 3 \
  --seed 530 \
  --format jsonl \
  --output generated-events.jsonl
```

Run the tests:

```bash
make test
```

Start the Push 4 API:

```bash
make api
```

After the server starts, open the interactive API docs at:

```text
http://127.0.0.1:8000/docs
```

Remove Python caches and test artifacts:

```bash
make clean
```

## CI

GitHub Actions runs `make install` and `make all` automatically on every push
and pull request using `.github/workflows/tests.yml`.

## Project Structure

- `/.github/workflows/tests.yml`: GitHub Actions workflow for validation and tests
- `/schemas/events.schema.json`: the versioned JSON Schema for all supported events
- `/src/image_retrieval/events.py`: JSON Schema loading and validation helpers
- `/src/image_retrieval/failure.py`: failure injection helpers for resilience tests
- `/src/image_retrieval/embedding.py`: Push 8 deterministic embedding service
- `/src/image_retrieval/vector_index.py`: Push 9 vector index service
- `/src/image_retrieval/pipeline.py`: deterministic in-memory retrieval pipeline
- `/src/image_retrieval/storage.py`: Push 7 document database and annotation storage
- `/src/image_retrieval/query.py`: Push 10 query service and image metadata loader
- `/src/image_retrieval/generator.py`: Push 5 synthetic event generator
- `/src/image_retrieval/demo.py`: CLI for validation, demos, generation, and queries
- `/src/image_retrieval/api.py`: FastAPI REST API for Push 4, Push 6, and Push 7
- `/tests/test_push3_pipeline.py`: validation and pipeline unit tests
- `/tests/test_push4_api.py`: API unit tests
- `/tests/test_push5_generator.py`: synthetic event generator unit tests
- `/tests/test_push6_inference.py`: upload plus inference flow unit tests
- `/tests/test_push7_storage.py`: document database and annotation storage tests
- `/tests/test_push8_9_services.py`: embedding service and vector index service tests
- `/tests/test_push10_query_cli.py`: query service and CLI tests
- `/tests/test_push11_idempotency.py`: idempotency and malformed-event handling tests
- `/tests/test_final_integration.py`: failure injection and end-to-end integration tests
- `/Makefile`: common project commands for install, validation, tests, API, and cleanup
- `/.gitignore`: local Python, cache, environment, and editor ignore rules
- `/examples/image.uploaded.json`: sample upload event
- `/examples/image.indexed.json`: sample indexing event
- `/examples/retrieval.requested.json`: sample retrieval request event
- `/examples/retrieval.completed.json`: sample retrieval result event

## Pipeline Flow

1. An image is uploaded into storage and represented as an `image.uploaded`
   event.
2. The image metadata is embedded and stored in the in-memory index, producing
   an `image.indexed` event.
3. A user submits a text retrieval query through a `retrieval.requested` event.
4. The retrieval pipeline ranks indexed images and emits a
   `retrieval.completed` event with scored matches.
5. The Push 5 generator can synthesize the same event flow as either a JSON
   array or newline-delimited JSON for repeatable local testing.
6. The Push 6 flow uploads a query image, indexes it, creates an image-based
   `retrieval.requested` event, and returns a `retrieval.completed` event with
   similar indexed images.
7. The Push 7 document store persists image metadata, index metadata, and
   human or model annotations as image-attached JSON documents.
8. The Push 8 embedding service converts text and image metadata into
   deterministic vectors.
9. The Push 9 vector index stores embeddings and ranks matches with cosine
   similarity.
10. The Push 10 query service wraps indexing and retrieval into a reusable
    search interface, with a CLI command for local text queries.
11. The Push 11 ingestion boundary validates incoming events, deduplicates by
    `event_id`, and returns structured malformed-event errors.
12. The final push adds deterministic failure injection points and integration
    coverage across event ingestion, API retrieval, and CLI query flows.

## API Endpoints

- `GET /health`: check service health and current in-memory index state
- `POST /images`: upload image metadata and automatically index it
- `GET /images`: list stored image documents
- `GET /images/{image_id}`: fetch one stored image document
- `POST /images/{image_id}/annotations`: attach an annotation to an image
- `GET /images/{image_id}/annotations`: list annotations for an image
- `POST /embeddings/text`: embed text with the Push 8 embedding service
- `POST /embeddings/image`: embed image metadata with the Push 8 embedding service
- `GET /vector-index`: inspect Push 9 vector index metadata
- `POST /vector-index`: upsert a vector into the Push 9 vector index
- `POST /vector-index/search`: search the Push 9 vector index
- `POST /retrievals`: submit a text query and receive ranked image matches
- `POST /inferences`: upload an image and run image-query retrieval in one flow
- `GET /events`: list schema-valid events emitted since the API started
- `POST /events`: ingest one event idempotently and emit downstream events when applicable

Example upload:

```bash
curl -X POST http://127.0.0.1:8000/images \
  -H "Content-Type: application/json" \
  -d '{
    "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
    "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
    "content_type": "image/jpeg",
    "width": 1920,
    "height": 1080,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "building"],
    "trace_id": "trace-api-demo"
  }'
```

Example retrieval:

```bash
curl -X POST http://127.0.0.1:8000/retrievals \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "red brick campus building",
    "top_k": 3,
    "requested_by": "student@example.edu",
    "trace_id": "trace-api-demo"
  }'
```

Example upload plus inference:

```bash
curl -X POST http://127.0.0.1:8000/inferences \
  -H "Content-Type: application/json" \
  -d '{
    "image_id": "f3726f40-6bb5-40b8-8eb0-c43c744d4f73",
    "storage_uri": "s3://ec530-images/uploads/new-campus-building.jpg",
    "content_type": "image/jpeg",
    "width": 1800,
    "height": 1200,
    "uploaded_by": "student@example.edu",
    "tags": ["campus", "brick", "outdoor"],
    "top_k": 3,
    "requested_by": "student@example.edu",
    "trace_id": "trace-inference-demo"
  }'
```

Example annotation:

```bash
curl -X POST http://127.0.0.1:8000/images/80253575-f761-4a68-a20f-75a66dcf0c88/annotations \
  -H "Content-Type: application/json" \
  -d '{
    "label": "campus-building",
    "annotator": "reviewer@example.edu",
    "confidence": 0.9,
    "notes": "Brick academic building.",
    "metadata": {"source": "manual-review"}
  }'
```

Example event ingestion:

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d @examples/image.uploaded.json
```

## Event Envelope

Every event uses the same top-level envelope:

- `schema_version`: schema version string, currently `1.0.0`
- `event_id`: globally unique identifier for the event
- `event_name`: event type name
- `event_version`: version of the event contract for that event type
- `occurred_at`: RFC 3339 timestamp in UTC
- `source`: service or component that emitted the event
- `trace_id`: optional identifier for correlating related events
- `payload`: event-specific data

## Implementation History

- Push 2 added the shared event schema and example event documents.
- Push 3 added executable validation, a local retrieval pipeline, a CLI demo,
  and unit tests.
- Push 4 added a FastAPI service with upload, retrieval, health, and event
  inspection endpoints.
- Push 5 added a synthetic event generator that emits schema-valid pipeline
  event streams from the CLI or Python API.
- Push 6 added an upload plus inference flow that indexes a submitted image and
  immediately runs image-query retrieval against the current index.
- Push 7 added a document-style image store with index metadata and image-level
  annotation storage, exposed through the REST API.
- Push 8 added a deterministic embedding service for text and image metadata.
- Push 9 added an in-memory vector index service for cosine-similarity search.
- Push 10 added a query service and CLI command for ranked text search.
- Push 11 added idempotent event ingestion and structured malformed-event
  handling for pipeline and API inputs.
- The final push added failure injection hooks and integration tests for
  ingestion retries, API 503 responses, and CLI query smoke coverage.

## Assumptions

Because the repository did not yet contain a project brief or existing schema,
the current design assumes an event-driven image retrieval workflow:

1. An image is uploaded into storage.
2. The image is embedded and indexed for search.
3. A user submits a retrieval query.
4. The system returns ranked matches.
