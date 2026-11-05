import gzip
import json
import tempfile
import unittest
from pathlib import Path

from apps.api.app.ingestion.uk_contracts_finder import (
    read_summaries,
    summarize_notice,
)


class PublicNoticeTests(unittest.TestCase):
    def test_summary_preserves_award_meaning(self):
        record = {
            "ocid": "ocds-example-1",
            "tender": {"id": "T-1", "title": "Training", "items": [{"id": "1"}]},
            "awards": [{
                "id": "A-1",
                "value": {"amount": 469128, "currency": "GBP"},
                "suppliers": [{"id": "S-1", "name": "Example Supplier"}],
                "documents": [{"url": "https://example.org/notice"}],
            }],
        }

        summary = summarize_notice(record)

        self.assertEqual(summary["tender_item_count"], 1)
        self.assertEqual(summary["awards"][0]["amount"], "469128")
        self.assertEqual(summary["awards"][0]["currency"], "GBP")
        self.assertEqual(summary["awards"][0]["suppliers"][0]["id"], "S-1")
        self.assertNotIn("invoice_price", summary)

    def test_stream_limit_and_missing_award(self):
        records = [
            {"ocid": "one", "tender": {"id": "T-1"}},
            {"ocid": "two", "awards": [{"id": "A-2"}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as output:
                for record in records:
                    output.write(json.dumps(record) + "\n")

            summaries = list(read_summaries(path, limit=1))

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["ocid"], "one")
        self.assertEqual(summaries[0]["awards"], [])