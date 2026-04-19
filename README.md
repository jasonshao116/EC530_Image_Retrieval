# EC530_Image_Retrieval

## Push 2: Event Schema

This repository now includes a first-pass event contract for an image retrieval
system. The schema is designed around a simple event envelope with strongly
typed payloads for the core pipeline stages:

- `image.uploaded`
- `image.indexed`
- `retrieval.requested`
- `retrieval.completed`

The schema files live in `/schemas`, and sample events live in `/examples`.

## Push 3: Validation and Local Retrieval Pipeline

Push 3 adds executable code around the event contract:

- validates event JSON files against `/schemas/events.schema.json`
- runs a deterministic in-memory image retrieval demo
- emits schema-valid events for upload, indexing, retrieval request, and retrieval completion
- includes unit tests for the examples and retrieval pipeline

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

## Run Push 3

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

## Files

- `/schemas/events.schema.json`: the versioned JSON Schema for all supported events
- `/src/image_retrieval/events.py`: JSON Schema loading and validation helpers
- `/src/image_retrieval/pipeline.py`: deterministic in-memory retrieval pipeline
- `/src/image_retrieval/demo.py`: CLI for validation and demo retrieval
- `/tests/test_push3_pipeline.py`: Push 3 unit tests
- `/examples/image.uploaded.json`: sample upload event
- `/examples/image.indexed.json`: sample indexing event
- `/examples/retrieval.requested.json`: sample retrieval request event
- `/examples/retrieval.completed.json`: sample retrieval result event

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

## Assumptions

Because the repository did not yet contain a project brief or existing schema,
the current design assumes an event-driven image retrieval workflow:

1. An image is uploaded into storage.
2. The image is embedded and indexed for search.
3. A user submits a retrieval query.
4. The system returns ranked matches.

If your course spec uses different event names or required fields, the schema is
set up so we can adjust it quickly without needing to redesign the full layout.
