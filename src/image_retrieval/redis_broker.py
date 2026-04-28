"""Redis Streams adapter for durable image retrieval events."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterable, Iterator
from typing import Any

import redis

from .events import validate_event


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_CONSUMER_GROUP = "image-retrieval-workers"
DEFAULT_STREAM_MAXLEN = 1000


class RedisEventBroker:
    """Publish and consume events using Redis Streams and a consumer group."""

    def __init__(
        self,
        redis_url: str = DEFAULT_REDIS_URL,
        *,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        consumer_name: str | None = None,
        stream_maxlen: int = DEFAULT_STREAM_MAXLEN,
        read_block_ms: int = 1000,
        client: Any | None = None,
    ) -> None:
        self.client = client or redis.Redis.from_url(redis_url, decode_responses=True)
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or os.getenv(
            "IMAGE_RETRIEVAL_STREAM_CONSUMER_NAME",
            socket.gethostname(),
        )
        self.stream_maxlen = stream_maxlen
        self.read_block_ms = read_block_ms
        self._pending_ids: dict[str, tuple[str, str]] = {}

    def publish(self, event: dict[str, Any]) -> None:
        validated_event = validate_event(event)
        stream = validated_event["event_name"]
        payload = json.dumps(validated_event, separators=(",", ":"))
        self.client.xadd(
            stream,
            {"event": payload},
            maxlen=self.stream_maxlen,
            approximate=True,
        )

    def listen(self, channels: Iterable[str]) -> Iterator[dict[str, Any]]:
        subscribed_channels = tuple(channels)
        for channel in subscribed_channels:
            self._ensure_group(channel)

        pending_streams = {channel: "0" for channel in subscribed_channels}
        while True:
            messages = self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams=pending_streams,
                count=1,
                block=1,
            )
            if not messages:
                break
            yield from self._decode_messages(messages)

        new_streams = {channel: ">" for channel in subscribed_channels}
        while True:
            messages = self.client.xreadgroup(
                groupname=self.consumer_group,
                consumername=self.consumer_name,
                streams=new_streams,
                count=1,
                block=self.read_block_ms,
            )
            if not messages:
                continue
            yield from self._decode_messages(messages)

    def acknowledge(self, event: dict[str, Any]) -> None:
        event_id = event.get("event_id")
        if not isinstance(event_id, str):
            return
        pending = self._pending_ids.pop(event_id, None)
        if pending is None:
            return
        stream, message_id = pending
        self.client.xack(stream, self.consumer_group, message_id)

    def _decode_messages(self, messages: list[tuple[str, list[tuple[str, dict[str, Any]]]]]) -> Iterator[dict[str, Any]]:
        for stream, entries in messages:
            for message_id, fields in entries:
                raw_event = fields["event"]
                event = validate_event(json.loads(raw_event))
                self._pending_ids[event["event_id"]] = (stream, message_id)
                yield event

    def _ensure_group(self, stream: str) -> None:
        try:
            self.client.xgroup_create(
                name=stream,
                groupname=self.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
