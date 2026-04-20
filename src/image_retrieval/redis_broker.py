"""Redis Pub/Sub adapter for image retrieval events."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

import redis

from .events import validate_event


DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class RedisEventBroker:
    """Publish and consume events using Redis channels named by event_name."""

    def __init__(self, redis_url: str = DEFAULT_REDIS_URL) -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def publish(self, event: dict[str, Any]) -> None:
        validated_event = validate_event(event)
        channel = validated_event["event_name"]
        self.client.publish(channel, json.dumps(validated_event, separators=(",", ":")))

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        pubsub = self.client.pubsub()
        pubsub.subscribe(*tuple(channels))

        try:
            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw_event = json.loads(message["data"])
                yield validate_event(raw_event)
        finally:
            pubsub.close()
