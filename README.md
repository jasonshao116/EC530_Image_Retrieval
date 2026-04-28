# EC530 Image Retrieval

Event-driven image retrieval prototype for uploading images, storing metadata,
building deterministic embeddings, and retrieving similar images through a web
UI, REST endpoints, or CLI tools.

The pipeline emits four event types, all validated against
`schemas/events.schema.json`:

- `image.uploaded`
- `image.indexed`
- `retrieval.requested`
- `retrieval.completed`

## Run The Pipeline

Create `.env` in the project root:

```text
MONGODB_URI=mongodb+srv://YOUR_USER:YOUR_PASSWORD@YOUR_CLUSTER/YOUR_DATABASE
MONGODB_DATABASE=ec530_image_retrieval
IMAGE_RETRIEVAL_DOCUMENT_STORE=mongo
IMAGE_RETRIEVAL_EVENT_BROKER=mongo

REDIS_URL=redis://default:YOUR_PASSWORD@YOUR_HOST:YOUR_PORT
IMAGE_RETRIEVAL_VECTOR_INDEX=redis
REDIS_VECTOR_NAMESPACE=ec530-image-retrieval
IMAGE_RETRIEVAL_UPLOAD_DIR=data/uploads
```

Install dependencies and start the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
make app
```

Open:

```text
http://127.0.0.1:8000/
```

The browser upload flow runs end to end: image metadata goes to MongoDB, vectors
and embeddings go to Redis, the image is indexed, and matches are returned.

To process queued MongoDB events asynchronously, run the worker in a second
terminal:

```bash
source .venv/bin/activate
make worker
```

## Storage

- MongoDB stores image metadata documents, image IDs, annotations, and event streams.
- Redis stores vectors and embeddings for similarity search.
- Uploaded image files are saved locally under `data/uploads/`; databases store references to those files, not the image bytes.
- On startup, the app loads stored MongoDB image documents and rebuilds the configured vector index.

By default, tests and local demos can still use in-memory storage. The `.env`
above enables the MongoDB + Redis split.

## Upload UI

The upload page supports:

- Uploading a local image with tags, uploader, and Top K.
- Viewing emitted pipeline events.
- Viewing ranked matches with thumbnails and scores.
- Reusing any existing uploaded image as the query image.

If `Matches` says `No other indexed images yet`, upload at least two images or
restart the app with MongoDB documents available so startup re-indexing can
populate the vector index.

## Worker

With `IMAGE_RETRIEVAL_EVENT_BROKER=mongo`, events are written to the MongoDB
events collection. The worker consumes:

- `image.uploaded`
- `retrieval.requested`

It publishes downstream:

- `image.indexed`
- `retrieval.completed`

Run it with:

```bash
make worker
```

`make redis-worker` remains as a compatibility alias for `make worker`.

## Useful Commands

```bash
make test      # run unit and integration tests
make all       # validate examples, run tests, check OpenAPI import
make demo      # run local retrieval demo
make infer     # run upload plus inference demo
make query     # run query CLI
make generate  # generate synthetic events
make clean     # remove caches and test artifacts
```

Check database connections:

```bash
PYTHONPATH=src .venv/bin/python -c "from pymongo import MongoClient; from image_retrieval.config import load_dotenv; import os; load_dotenv(); print(MongoClient(os.environ['MONGODB_URI']).admin.command('ping'))"
PYTHONPATH=src .venv/bin/python -c "import redis; from image_retrieval.config import load_dotenv; import os; load_dotenv(); print(redis.Redis.from_url(os.environ['REDIS_URL'], decode_responses=True).ping())"
```

Open API docs after starting the app:

```text
http://127.0.0.1:8000/docs
```

## API Endpoints

- `GET /health`: service health, stored image count, indexed image count, and event count
- `GET /`: browser upload UI
- `POST /uploads`: upload an image file and retrieve matches
- `GET /images`: list stored image documents
- `POST /images`: upload image metadata
- `GET /images/{image_id}`: fetch one image document
- `POST /images/{image_id}/retrievals`: retrieve matches using an existing image
- `POST /images/{image_id}/annotations`: add an annotation
- `GET /images/{image_id}/annotations`: list annotations
- `POST /embeddings/text`: embed text
- `POST /embeddings/image`: embed image metadata
- `GET /vector-index`: inspect vector index stats
- `POST /vector-index`: upsert a vector manually
- `POST /vector-index/search`: search vectors manually
- `POST /retrievals`: submit a text query
- `POST /inferences`: upload image metadata and run image-query retrieval
- `GET /events`: list events emitted since startup
- `POST /events`: ingest one event idempotently

Example upload:

```bash
curl -X POST http://127.0.0.1:8000/uploads \
  -F "file=@/path/to/your/image.jpg" \
  -F "tags=campus, brick, outdoor" \
  -F "uploaded_by=student@example.edu" \
  -F "top_k=3"
```

Example text retrieval:

```bash
curl -X POST http://127.0.0.1:8000/retrievals \
  -H "Content-Type: application/json" \
  -d '{
    "query_text": "red brick campus building",
    "top_k": 3,
    "requested_by": "student@example.edu"
  }'
```

## Project Structure

- `src/image_retrieval/api.py`: FastAPI app and browser upload UI
- `src/image_retrieval/pipeline.py`: upload, indexing, retrieval, and re-indexing pipeline
- `src/image_retrieval/storage.py`: in-memory, file-backed, Redis, and MongoDB document stores
- `src/image_retrieval/vector_index.py`: in-memory and Redis-backed vector indexes
- `src/image_retrieval/broker.py`: broker interface, in-memory broker, and MongoDB event broker
- `src/image_retrieval/redis_broker.py`: Redis Streams event broker
- `src/image_retrieval/worker.py`: event worker
- `src/image_retrieval/embedding.py`: deterministic embedding service
- `src/image_retrieval/query.py`: query service and image metadata loader
- `src/image_retrieval/demo.py`: CLI entry point
- `schemas/events.schema.json`: event schema
- `examples/`: sample event JSON files
- `tests/`: unit and integration tests
- `Makefile`: common commands

## Event Envelope

Every event uses these top-level fields:

- `schema_version`
- `event_id`
- `event_name`
- `event_version`
- `occurred_at`
- `source`
- `trace_id`
- `payload`
