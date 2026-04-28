"""Broker abstractions for event-driven image retrieval services."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
import os
import time
from typing import Any, Protocol

from .events import validate_event


class EventBroker(Protocol):
    """Common interface for publishing and consuming schema-valid events."""

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event to the channel matching its event name."""

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        """Yield events from the requested channels."""

    def acknowledge(self, event: dict[str, Any]) -> None:
        """Mark a previously delivered event as processed."""


class InMemoryEventBroker:
    """Small broker implementation for unit tests and local dry runs."""

    def __init__(self) -> None:
        self._channels: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self.published_events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        validated_event = validate_event(event)
        channel = validated_event["event_name"]
        self._channels[channel].append(validated_event)
        self.published_events.append(validated_event)

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        subscribed_channels = tuple(channels)
        while True:
            for channel in subscribed_channels:
                if self._channels[channel]:
                    yield self._channels[channel].popleft()
                    break
            else:
                return

    def acknowledge(self, event: dict[str, Any]) -> None:
        return None


class MongoEventBroker:
    """MongoDB-backed event stream adapter."""

    def __init__(
        self,
        mongo_uri: str,
        *,
        database_name: str = "image_retrieval",
        events_collection: str = "events",
        consumer_name: str | None = None,
        poll_interval_seconds: float = 1.0,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from pymongo import MongoClient

            client = MongoClient(mongo_uri)
        self.client = client
        self.database_name = database_name
        self.events_collection_name = events_collection
        self.consumer_name = consumer_name or os.getenv("IMAGE_RETRIEVAL_MONGO_CONSUMER_NAME", "image-retrieval-worker")
        self.poll_interval_seconds = poll_interval_seconds
        self.events = self.client[database_name][events_collection]

    def publish(self, event: dict[str, Any]) -> None:
        validated_event = validate_event(event)
        self.events.replace_one(
            {"event_id": validated_event["event_id"]},
            {
                "event_id": validated_event["event_id"],
                "event_name": validated_event["event_name"],
                "channel": validated_event["event_name"],
                "event": validated_event,
                "published_at": datetime.now(UTC),
                "acknowledged_by": [],
            },
            upsert=True,
        )

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        subscribed_channels = tuple(channels)
        while True:
            document = self.events.find_one(
                {
                    "channel": {"$in": list(subscribed_channels)},
                    "acknowledged_by": {"$ne": self.consumer_name},
                },
                sort=[("published_at", 1), ("event_id", 1)],
            )
            if document is None:
                time.sleep(self.poll_interval_seconds)
                continue
            yield validate_event(document["event"])

    def acknowledge(self, event: dict[str, Any]) -> None:
        event_id = event.get("event_id")
        if not isinstance(event_id, str):
            return
        self.events.update_one(
            {"event_id": event_id},
            {"$addToSet": {"acknowledged_by": self.consumer_name}},
        )
