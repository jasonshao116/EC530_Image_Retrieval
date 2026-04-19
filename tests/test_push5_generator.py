from __future__ import annotations

import io
import json
import unittest

from image_retrieval.events import validate_event
from image_retrieval.generator import generate_event_stream, write_events


class EventGeneratorTests(unittest.TestCase):
    def test_generator_emits_schema_valid_pipeline_events(self) -> None:
        events = generate_event_stream(image_count=2, retrieval_count=1, top_k=2, seed=530)

        self.assertEqual(
            [event["event_name"] for event in events],
            [
                "image.uploaded",
                "image.indexed",
                "image.uploaded",
                "image.indexed",
                "retrieval.requested",
                "retrieval.completed",
            ],
        )
        for event in events:
            self.assertIs(validate_event(event), event)
            self.assertEqual(event["source"], "push5-event-generator")
            self.assertEqual(event["trace_id"], "trace-push5-generator")

        completed_event = events[-1]
        self.assertEqual(completed_event["payload"]["result_count"], 2)
        self.assertEqual(len(completed_event["payload"]["results"]), 2)

    def test_generator_rejects_invalid_counts(self) -> None:
        with self.assertRaises(ValueError):
            generate_event_stream(image_count=0)

        with self.assertRaises(ValueError):
            generate_event_stream(retrieval_count=-1)

        with self.assertRaises(ValueError):
            generate_event_stream(top_k=0)

    def test_write_events_supports_jsonl(self) -> None:
        events = generate_event_stream(image_count=1, retrieval_count=0, seed=530)
        output = io.StringIO()

        write_events(events, output, output_format="jsonl")

        lines = output.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["event_name"], "image.uploaded")
        self.assertEqual(json.loads(lines[1])["event_name"], "image.indexed")


if __name__ == "__main__":
    unittest.main()
