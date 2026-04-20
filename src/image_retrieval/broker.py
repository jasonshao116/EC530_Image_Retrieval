"""Broker abstractions for event-driven image retrieval services."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from .events import validate_event


class EventBroker(Protocol):
    """Common interface for publishing and consuming schema-valid events."""

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event to the channel matching its event name."""

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        """Yield events from the requested channels."""


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
