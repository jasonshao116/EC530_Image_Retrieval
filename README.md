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

## Files

- `/schemas/events.schema.json`: the versioned JSON Schema for all supported events
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
