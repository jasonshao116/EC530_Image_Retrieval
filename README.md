# EC530_Image_Retrieval

This repository contains an event-driven image retrieval prototype. It combines
the Push 2 event schema, the Push 3 executable validation and local retrieval
pipeline, and the Push 4 REST API.

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

## Project Structure

- `/schemas/events.schema.json`: the versioned JSON Schema for all supported events
- `/src/image_retrieval/events.py`: JSON Schema loading and validation helpers
- `/src/image_retrieval/pipeline.py`: deterministic in-memory retrieval pipeline
- `/src/image_retrieval/demo.py`: CLI for validation and demo retrieval
- `/src/image_retrieval/api.py`: FastAPI REST API for Push 4
- `/tests/test_push3_pipeline.py`: validation and pipeline unit tests
- `/tests/test_push4_api.py`: API unit tests
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

## API Endpoints

- `GET /health`: check service health and current in-memory index state
- `POST /images`: upload image metadata and automatically index it
- `POST /retrievals`: submit a text query and receive ranked image matches
- `GET /events`: list schema-valid events emitted since the API started

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

## Assumptions

Because the repository did not yet contain a project brief or existing schema,
the current design assumes an event-driven image retrieval workflow:

1. An image is uploaded into storage.
2. The image is embedded and indexed for search.
3. A user submits a retrieval query.
4. The system returns ranked matches.

If your course spec uses different event names or required fields, the schema is
set up so we can adjust it quickly without needing to redesign the full layout.
