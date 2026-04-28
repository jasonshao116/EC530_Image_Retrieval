from __future__ import annotations

import copy
import unittest

from image_retrieval.broker import InMemoryEventBroker, MongoEventBroker
from image_retrieval.events import EventValidationError
from image_retrieval.pipeline import ImageRetrievalPipeline
from image_retrieval.redis_broker import RedisEventBroker
from image_retrieval.worker import process_and_publish


IMAGE_UPLOADED_EVENT = {
    "schema_version": "1.0.0",
    "event_id": "22222222-2222-4222-8222-222222222222",
    "event_name": "image.uploaded",
    "event_version": "1.0.0",
    "occurred_at": "2026-04-14T20:00:00Z",
    "source": "redis-broker-test",
    "trace_id": "trace-redis",
    "payload": {
        "image": {
            "image_id": "80253575-f761-4a68-a20f-75a66dcf0c88",
            "storage_uri": "s3://ec530-images/dataset/campus-001.jpg",
            "content_type": "image/jpeg",
            "width": 1920,
            "height": 1080,
            "uploaded_by": "student@example.edu",
            "tags": ["campus", "brick", "building"],
        }
    },
}


class BrokerTests(unittest.TestCase):
    def test_in_memory_broker_routes_by_event_name(self) -> None:
        broker = InMemoryEventBroker()

        broker.publish(copy.deepcopy(IMAGE_UPLOADED_EVENT))
        events = list(broker.listen(["image.uploaded"]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_name"], "image.uploaded")
        self.assertEqual(events[0]["event_id"], IMAGE_UPLOADED_EVENT["event_id"])

    def test_in_memory_broker_validates_before_publish(self) -> None:
        broker = InMemoryEventBroker()
        bad_event = copy.deepcopy(IMAGE_UPLOADED_EVENT)
        bad_event["event_id"] = "not-a-uuid"

        with self.assertRaises(EventValidationError):
            broker.publish(bad_event)

    def test_worker_processes_and_publishes_downstream_events(self) -> None:
        broker = InMemoryEventBroker()
        pipeline = ImageRetrievalPipeline(source="redis-worker-test")

        result = process_and_publish(
            copy.deepcopy(IMAGE_UPLOADED_EVENT),
            pipeline=pipeline,
            broker=broker,
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["emitted_events"][0]["event_name"], "image.indexed")
        self.assertEqual(broker.published_events[0]["event_name"], "image.indexed")
        self.assertEqual(pipeline.index.image_count, 1)


class FakeRedisResponseError(Exception):
    pass


class FakeRedisStreamClient:
    def __init__(self) -> None:
        self.groups: set[tuple[str, str]] = set()
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.pending: dict[tuple[str, str, str], list[tuple[str, dict[str, str]]]] = {}
        self.acked: list[tuple[str, str, str]] = []
        self._next_id = 1

    def xadd(self, stream: str, fields: dict[str, str], maxlen: int | None = None, approximate: bool = True) -> str:
        message_id = f"{self._next_id}-0"
        self._next_id += 1
        entries = self.streams.setdefault(stream, [])
        entries.append((message_id, dict(fields)))
        if maxlen is not None and len(entries) > maxlen:
            del entries[:-maxlen]
        return message_id

    def xgroup_create(self, name: str, groupname: str, id: str = "0", mkstream: bool = True) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise FakeRedisResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)
        if mkstream:
            self.streams.setdefault(name, [])

    def xreadgroup(
        self,
        *,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int = 1,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        del block
        for stream, stream_id in streams.items():
            key = (stream, groupname, consumername)
            if stream_id == "0":
                entries = self.pending.get(key, [])
                if entries:
                    return [(stream, entries[:count])]
                continue

            if stream_id == ">":
                delivered = self.pending.setdefault(key, [])
                delivered_ids = {message_id for message_id, _ in delivered}
                available = [
                    (message_id, fields)
                    for message_id, fields in self.streams.get(stream, [])
                    if message_id not in delivered_ids
                ]
                if available:
                    chunk = available[:count]
                    delivered.extend(chunk)
                    return [(stream, chunk)]
        return []

    def xack(self, stream: str, groupname: str, message_id: str) -> int:
        removed = 0
        for key, entries in self.pending.items():
            stream_name, pending_group, _consumer_name = key
            if stream_name != stream or pending_group != groupname:
                continue
            before = len(entries)
            entries[:] = [entry for entry in entries if entry[0] != message_id]
            if len(entries) != before:
                removed += 1
        self.acked.append((stream, groupname, message_id))
        return removed


class RedisStreamBrokerTests(unittest.TestCase):
    def test_stream_broker_publishes_listens_and_acknowledges(self) -> None:
        client = FakeRedisStreamClient()
        broker = RedisEventBroker(
            "redis://example.invalid:6379/0",
            consumer_group="test-workers",
            consumer_name="worker-a",
            client=client,
        )

        broker.publish(copy.deepcopy(IMAGE_UPLOADED_EVENT))
        event = next(broker.listen(["image.uploaded"]))

        self.assertEqual(event["event_name"], "image.uploaded")
        self.assertEqual(event["event_id"], IMAGE_UPLOADED_EVENT["event_id"])

        broker.acknowledge(event)

        self.assertEqual(client.acked, [("image.uploaded", "test-workers", "1-0")])

    def test_stream_broker_replays_unacked_pending_message_for_same_consumer(self) -> None:
        client = FakeRedisStreamClient()
        broker = RedisEventBroker(
            "redis://example.invalid:6379/0",
            consumer_group="test-workers",
            consumer_name="worker-a",
            client=client,
        )

        broker.publish(copy.deepcopy(IMAGE_UPLOADED_EVENT))
        first = next(broker.listen(["image.uploaded"]))
        self.assertEqual(first["event_id"], IMAGE_UPLOADED_EVENT["event_id"])

        restarted_broker = RedisEventBroker(
            "redis://example.invalid:6379/0",
            consumer_group="test-workers",
            consumer_name="worker-a",
            client=client,
        )
        replayed = next(restarted_broker.listen(["image.uploaded"]))

        self.assertEqual(replayed["event_id"], IMAGE_UPLOADED_EVENT["event_id"])


class FakeMongoEventCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}

    def replace_one(self, query: dict[str, object], document: dict[str, object], upsert: bool = False) -> None:
        del upsert
        event_id = str(query["event_id"])
        self.documents[event_id] = dict(document)

    def find_one(
        self,
        query: dict[str, object],
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, object] | None:
        del sort
        channels = set(query["channel"]["$in"])
        consumer_name = query["acknowledged_by"]["$ne"]
        for document in self.documents.values():
            if document["channel"] in channels and consumer_name not in document["acknowledged_by"]:
                return dict(document)
        return None

    def update_one(self, query: dict[str, object], update: dict[str, object]) -> None:
        document = self.documents[str(query["event_id"])]
        document.setdefault("acknowledged_by", [])
        consumer_name = update["$addToSet"]["acknowledged_by"]
        if consumer_name not in document["acknowledged_by"]:
            document["acknowledged_by"].append(consumer_name)


class FakeMongoEventDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeMongoEventCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoEventCollection:
        return self.collections.setdefault(name, FakeMongoEventCollection())


class FakeMongoEventClient:
    def __init__(self) -> None:
        self.databases: dict[str, FakeMongoEventDatabase] = {}

    def __getitem__(self, name: str) -> FakeMongoEventDatabase:
        return self.databases.setdefault(name, FakeMongoEventDatabase())


class MongoEventBrokerTests(unittest.TestCase):
    def test_mongo_broker_publishes_listens_and_acknowledges(self) -> None:
        client = FakeMongoEventClient()
        broker = MongoEventBroker(
            "mongodb://example.invalid:27017",
            database_name="test-db",
            consumer_name="worker-a",
            poll_interval_seconds=0,
            client=client,
        )

        broker.publish(copy.deepcopy(IMAGE_UPLOADED_EVENT))
        event = next(broker.listen(["image.uploaded"]))
        broker.acknowledge(event)

        self.assertEqual(event["event_id"], IMAGE_UPLOADED_EVENT["event_id"])
        stored = client["test-db"]["events"].documents[IMAGE_UPLOADED_EVENT["event_id"]]
        self.assertEqual(stored["channel"], "image.uploaded")
        self.assertEqual(stored["acknowledged_by"], ["worker-a"])


if __name__ == "__main__":
    unittest.main()
