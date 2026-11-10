"""Reader snapshots preserve review outcomes without transferring full model contexts."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from snapshot_projection import reader_events


class ReaderEventsTest(unittest.TestCase):
    def test_large_transcripts_remain_persisted_but_not_in_reader_payload(self):
        transcript = "原文" * 1_000_000
        events = [
            {"kind": "review_requested", "sequence": 1, "at": "date", "payload": {"messages": transcript, "execution_ref": "review"}},
            {"kind": "review_completed", "sequence": 2, "at": "date", "payload": {"output": transcript, "execution_ref": "review", "analysis_fingerprint": "current", "report_checks": [{"verdict": "failed"}], "section_checks": [{"verdict": "unclear"}]}},
            {"kind": "search_completed", "sequence": 3, "at": "date", "payload": {"sources": [{"url": "https://example.org"}], "truncated": True}},
        ]
        events.append({"kind": "review_failed", "sequence": 4, "at": "date", "payload": {"output": transcript, "error": "Invalid review", "code": "REVIEW_INVALID"}})
        events.extend([
            {"kind": "capability_requested", "sequence": 5, "at": "date", "payload": {"messages": transcript}},
            {"kind": "capability_completed", "sequence": 6, "at": "date", "payload": {"output": transcript}},
            {"kind": "capability_failed", "sequence": 7, "at": "date", "payload": {"output": transcript}},
        ])
        projected = reader_events(events)
        self.assertLess(len(json.dumps(projected)), 4096)
        self.assertEqual(events[0]["payload"]["messages"], transcript)
        self.assertEqual(events[1]["payload"]["output"], transcript)
        self.assertEqual(projected[1]["payload"]["report_checks"], [{"verdict": "failed"}])
        self.assertEqual(projected[1]["payload"]["section_checks"], [{"verdict": "unclear"}])
        self.assertEqual(projected[2], events[2])
        self.assertNotIn("output", projected[3]["payload"])
        self.assertEqual(events[3]["payload"]["output"], transcript)
        self.assertEqual(projected[3]["payload"]["error"], "Invalid review")
        self.assertNotIn("messages", projected[4]["payload"])
        self.assertNotIn("output", projected[5]["payload"])
        self.assertNotIn("output", projected[6]["payload"])


if __name__ == "__main__":
    unittest.main()
