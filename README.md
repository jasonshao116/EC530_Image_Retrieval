# EC530_Image_Retrieval

This repository contains an event-driven image retrieval prototype. It combines
the Push 2 event schema with the Push 3 executable validation and local
retrieval pipeline.

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

Validate the sample events:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo validate examples/*.json
```

Run the local retrieval demo:

```bash
PYTHONPATH=src python3 -m image_retrieval.demo demo --query "red brick campus building" --top-k 3
```

Run the tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Project Structure

- `/schemas/events.schema.json`: the versioned JSON Schema for all supported events
- `/src/image_retrieval/events.py`: JSON Schema loading and validation helpers
- `/src/image_retrieval/pipeline.py`: deterministic in-memory retrieval pipeline
- `/src/image_retrieval/demo.py`: CLI for validation and demo retrieval
- `/tests/test_push3_pipeline.py`: validation and pipeline unit tests
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

## Assumptions

Because the repository did not yet contain a project brief or existing schema,
the current design assumes an event-driven image retrieval workflow:

1. An image is uploaded into storage.
2. The image is embedded and indexed for search.
3. A user submits a retrieval query.
4. The system returns ranked matches.

If your course spec uses different event names or required fields, the schema is
set up so we can adjust it quickly without needing to redesign the full layout.
