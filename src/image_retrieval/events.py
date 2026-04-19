"""Helpers for loading and validating image retrieval events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "events.schema.json"


class EventValidationError(ValueError):
    """Raised when an event does not match the repository event schema."""


def load_schema(schema_path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Load the JSON Schema used by all Push 3 event validation."""

    with Path(schema_path).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def load_event(event_path: Path | str) -> dict[str, Any]:
    """Load a single event JSON document from disk."""

    with Path(event_path).open(encoding="utf-8") as event_file:
        return json.load(event_file)


def validate_event(
    event: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an event and return it unchanged when valid."""

    validator = Draft202012Validator(
        schema or load_schema(),
        format_checker=FormatChecker(),
    )

    try:
        validator.validate(event)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        location = f" at {path}" if path else ""
        raise EventValidationError(f"Invalid {event.get('event_name', 'event')}{location}: {exc.message}") from exc

    return event
