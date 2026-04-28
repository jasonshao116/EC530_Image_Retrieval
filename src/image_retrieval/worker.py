"""Redis Streams-backed worker for processing image retrieval events."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from typing import Any

from .broker import EventBroker
from .config import load_dotenv
from .pipeline import ImageRetrievalPipeline
from .storage import create_document_store_from_env


DEFAULT_REDIS_URL = "redis://localhost:6379/0"


DEFAULT_SUBSCRIPTIONS = ("image.uploaded", "retrieval.requested")


def process_and_publish(
    event: dict[str, Any],
    *,
    pipeline: ImageRetrievalPipeline,
    broker: EventBroker,
) -> dict[str, Any]:
    """Process one event and publish all downstream events."""

    result = pipeline.process_event(event)
    if result["accepted"]:
        for emitted_event in result["emitted_events"]:
            broker.publish(emitted_event)
        broker.acknowledge(event)
        return result

    return result


def run_worker(
    *,
    broker: EventBroker,
    pipeline: ImageRetrievalPipeline,
    channels: Iterable[str] = DEFAULT_SUBSCRIPTIONS,
) -> None:
    """Listen forever and process events from the configured broker."""

    subscribed_channels = tuple(channels)
    print(f"Listening for events on: {', '.join(subscribed_channels)}")
    for event in broker.listen(subscribed_channels):
        result = process_and_publish(event, pipeline=pipeline, broker=broker)
        print(
            json.dumps(
                {
                    "event_name": event.get("event_name"),
                    "event_id": event.get("event_id"),
                    "status": result["status"],
                    "emitted": [
                        emitted["event_name"]
                        for emitted in result.get("emitted_events", [])
                    ],
                },
                sort_keys=True,
            )
        )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the Redis event worker.")
    parser.add_argument(
        "--broker",
        choices=["redis", "mongo"],
        default=os.getenv("IMAGE_RETRIEVAL_EVENT_BROKER", "redis"),
        help="Event broker backend. Defaults to IMAGE_RETRIEVAL_EVENT_BROKER or redis.",
    )
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
        help="Redis connection URL. Defaults to REDIS_URL or localhost Redis.",
    )
    parser.add_argument(
        "--channel",
        action="append",
        dest="channels",
        help="Channel to subscribe to. Can be passed multiple times.",
    )
    args = parser.parse_args()

    if args.broker == "mongo":
        from .broker import MongoEventBroker

        mongo_uri = os.getenv("MONGODB_URI")
        if not mongo_uri:
            raise RuntimeError("MONGODB_URI is required when IMAGE_RETRIEVAL_EVENT_BROKER=mongo")
        broker = MongoEventBroker(
            mongo_uri,
            database_name=os.getenv("MONGODB_DATABASE", "image_retrieval"),
            events_collection=os.getenv("MONGODB_EVENTS_COLLECTION", "events"),
        )
    else:
        from .redis_broker import RedisEventBroker

        broker = RedisEventBroker(args.redis_url)
    pipeline = ImageRetrievalPipeline(
        source="redis-worker",
        document_store=create_document_store_from_env(),
    )
    pipeline.reindex_stored_images()
    run_worker(
        broker=broker,
        pipeline=pipeline,
        channels=args.channels or DEFAULT_SUBSCRIPTIONS,
    )


if __name__ == "__main__":
    main()
