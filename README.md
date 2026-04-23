# EC530 Image Retrieval

This project is an event-driven image retrieval prototype. It lets you upload
images, store their metadata, index them with deterministic embeddings, and
retrieve similar images through a web UI, REST API, or CLI.

The pipeline emits four event types:

- `image.uploaded`
- `image.indexed`
- `retrieval.requested`
- `retrieval.completed`

Each event uses a shared JSON envelope and is validated against the schema in
`schemas/events.schema.json`.

## Features

- Browser upload UI for laptop image uploads
- FastAPI REST API for uploads, retrievals, events, embeddings, vectors, and annotations
- Redis Cloud support for persisted image documents
- Local file storage for uploaded image files
- In-memory vector index for similarity search
- Startup re-indexing from stored image documents
- Deterministic text and image metadata embeddings
- Redis Pub/Sub adapter and worker for event processing
- CLI demos for validation, retrieval, generation, and query workflows
- Unit and integration tests for the full local pipeline

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

Run the test suite:

```bash
make test
```

Run validation, tests, and an API import check:

```bash
make all
```

## Upload UI

Start the API server:

```bash
make api
```

Open the upload page:

```text
http://127.0.0.1:8000/
```

Use the page like this:

1. Click `Choose File` and select an image from your laptop.
2. Enter tags such as `CR7`, `soccer`, or `campus`.
3. Enter who uploaded the image.
4. Choose `Top K`, which is the maximum number of similar images to return.
5. Click `Upload Image`.

After the upload completes, the page shows:

- `Pipeline Output`: the events emitted by the pipeline
- `Matches`: similar indexed images, with thumbnails, rank, and score
- `Uploaded Images`: images already stored by the app

If `Matches` says `No other indexed images yet`, the current vector index does
not have another image to compare against. Upload at least two images during the
same server run, or use Redis-backed startup re-indexing so previously stored
documents are indexed when the server starts.

## How Storage Works

The app uses two storage layers:

- The document store persists image metadata, index metadata, and annotations.
- The vector index stores embeddings used for similarity search.

By default, the document store is in memory. You can switch it to Redis Cloud
with `.env`.

Uploaded image files themselves are saved locally under `data/uploads/`. Redis
stores the records that point to those files; it does not store the image bytes.

When the API starts, it loads stored image documents and rebuilds the in-memory
vector index. This allows Redis Cloud records to become searchable again after a
restart.

## Redis Cloud

Create or edit the local `.env` file in the project root:

```text
REDIS_URL=redis://default:YOUR_PASSWORD@YOUR_HOST:YOUR_PORT
IMAGE_RETRIEVAL_DOCUMENT_STORE=redis
REDIS_NAMESPACE=ec530-image-retrieval
IMAGE_RETRIEVAL_UPLOAD_DIR=data/uploads
```

Use the exact Redis connection URL from the Redis Cloud `Connect` page. Some
Redis Cloud databases use `redis://`; TLS-enabled databases may use `rediss://`.
Match the scheme shown by Redis Cloud.

Do not commit `.env`. It contains your Redis password and is ignored by git.

Test the Redis connection:

```bash
PYTHONPATH=src .venv/bin/python -c "import redis; from image_retrieval.config import load_dotenv; import os; load_dotenv(); r=redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True); print(r.ping())"
```

Expected output:

```text
True
```

Then start the API:

```bash
make api
```

## Redis Pub/Sub Worker

Redis can also be used as the project message bus. Each Pub/Sub channel is named
after the event type, such as `image.uploaded` or `retrieval.requested`.

Run the worker:

```bash
make redis-worker
```

Publish one sample event:

```bash
make redis-publish
```

The worker subscribes to:

- `image.uploaded`
- `retrieval.requested`

It publishes downstream events such as:

- `image.indexed`
- `retrieval.completed`

Redis Pub/Sub is not durable. If a subscriber is offline, it can miss messages.
For production-style replay, Redis Streams or Kafka would be a stronger fit.

## Common Commands

Validate sample events:

```bash
make validate
```

Run the local retrieval demo:

```bash
make demo
```

Run the upload plus inference demo:

```bash
make infer
```

Run the query CLI:

```bash
make query
```

Generate synthetic events:

```bash
make generate
```

Open API docs after starting the server:

```text
http://127.0.0.1:8000/docs
```

Clean caches and test artifacts:

```bash
make clean
```

## API Endpoints

- `GET /health`: service health, stored image count, indexed image count, and event count
- `GET /`: browser upload UI
- `POST /uploads`: upload an image file from the browser or multipart form
- `POST /images`: upload image metadata and index it
- `GET /images`: list stored image documents
- `GET /images/{image_id}`: fetch one image document
- `POST /images/{image_id}/annotations`: add an annotation to an image
- `GET /images/{image_id}/annotations`: list annotations for an image
- `POST /embeddings/text`: embed text
- `POST /embeddings/image`: embed image metadata
- `GET /vector-index`: inspect vector index stats
- `POST /vector-index`: upsert a vector manually
- `POST /vector-index/search`: search vectors manually
- `POST /retrievals`: submit a text query and receive ranked matches
- `POST /inferences`: upload image metadata and run image-query retrieval
- `GET /events`: list events emitted since the API started
- `POST /events`: ingest one event idempotently

Multipart file upload example:

```bash
curl -X POST http://127.0.0.1:8000/uploads \
  -F "file=@/path/to/your/image.jpg" \
  -F "tags=campus, brick, outdoor" \
  -F "uploaded_by=student@example.edu" \
  -F "top_k=3"
```

Text retrieval example:

```bash
curl -X POST http://127.0.0.1:8000/retrievals \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "red brick campus building",
    "top_k": 3,
    "requested_by": "student@example.edu"
  }'
```

Annotation example:

```bash
curl -X POST http://127.0.0.1:8000/images/80253575-f761-4a68-a20f-75a66dcf0c88/annotations \
  -H "Content-Type: application/json" \
  -d '{
    "label": "campus-building",
    "annotator": "reviewer@example.edu",
    "confidence": 0.9,
    "notes": "Brick academic building."
  }'
```

Event ingestion example:

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d @examples/image.uploaded.json
```

## CLI Examples

Query a JSON file containing image metadata:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo query \
  "brick campus" \
  --images images.json \
  --top-k 3 \
  --format json
```

Generate newline-delimited JSON events:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo generate \
  --images 5 \
  --retrievals 3 \
  --top-k 3 \
  --seed 530 \
  --format jsonl \
  --output generated-events.jsonl
```

## Project Structure

- `.github/workflows/tests.yml`: GitHub Actions workflow
- `schemas/events.schema.json`: event schema
- `src/image_retrieval/api.py`: FastAPI app and browser upload UI
- `src/image_retrieval/config.py`: local `.env` loader
- `src/image_retrieval/events.py`: schema loading and validation
- `src/image_retrieval/pipeline.py`: upload, indexing, retrieval, and re-indexing pipeline
- `src/image_retrieval/storage.py`: in-memory, file-backed, and Redis document stores
- `src/image_retrieval/embedding.py`: deterministic embedding service
- `src/image_retrieval/vector_index.py`: cosine-similarity vector index
- `src/image_retrieval/query.py`: query service and image metadata loader
- `src/image_retrieval/broker.py`: broker interface and in-memory broker
- `src/image_retrieval/redis_broker.py`: Redis Pub/Sub adapter
- `src/image_retrieval/worker.py`: Redis worker
- `src/image_retrieval/generator.py`: synthetic event generator
- `src/image_retrieval/demo.py`: CLI entry point
- `scripts/publish_event.py`: publish one event JSON file to Redis
- `examples/`: sample event JSON files
- `tests/`: unit and integration tests
- `Makefile`: common commands

## Event Envelope

Every event uses these top-level fields:

- `schema_version`: schema version string, currently `1.0.0`
- `event_id`: globally unique event ID
- `event_name`: event type
- `event_version`: event contract version
- `occurred_at`: RFC 3339 timestamp in UTC
- `source`: service or component that emitted the event
- `trace_id`: optional correlation ID
- `payload`: event-specific data
