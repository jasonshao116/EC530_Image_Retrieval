"""Publish one schema-valid event JSON file to Redis."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from image_retrieval.events import load_event
from image_retrieval.redis_broker import DEFAULT_REDIS_URL, RedisEventBroker


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an event JSON file to Redis.")
    parser.add_argument("event_path", type=Path, help="Path to a JSON event file.")
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
        help="Redis connection URL. Defaults to REDIS_URL or localhost Redis.",
    )
    args = parser.parse_args()

    event = load_event(args.event_path)
    broker = RedisEventBroker(args.redis_url)
    broker.publish(event)
    print(f"Published {event['event_name']} event {event['event_id']}")


if __name__ == "__main__":
    main()
