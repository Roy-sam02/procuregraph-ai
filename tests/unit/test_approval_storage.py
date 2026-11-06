import unittest
from unittest.mock import MagicMock
from uuid import UUID

from apps.api.app.agents.investigation_records import record_approval


class ApprovalStorageTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.tenant, self.finding, self.actor = [UUID(int=n) for n in (1, 2, 3)]
        self.key = "synthetic-review-key-001"

    def record(self, **overrides):
        args = {"connection": self.connection, "tenant": self.tenant,
                "finding_id": self.finding, "actor_id": self.actor,
                "decision": "rejected", "reason": "Checked the contract", "key": self.key}
        return record_approval(**(args | overrides))

    def test_verified_tenant_lock_and_insert(self):
        self.cursor.fetchone.side_effect = [(self.finding,), (UUID(int=4),)]
        self.assertEqual(self.record(), UUID(int=4))
        query, parameters = self.cursor.execute.call_args_list[0].args
        self.assertIn("i.tenant_id = %s", query)
        self.assertIn("FOR UPDATE OF f", query)
        self.assertEqual(parameters, (self.finding, self.tenant))
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_wrong_tenant_or_unverified_finding_cannot_insert(self):
        self.cursor.fetchone.return_value = None
        with self.assertRaises(ValueError):
            self.record()
        self.assertEqual(self.cursor.execute.call_count, 1)

    def test_retry_and_conflicting_decision(self):
        original = (UUID(int=4), self.finding, self.actor, "rejected", "Checked the contract")
        self.cursor.fetchone.side_effect = [(self.finding,), None, original]
        self.assertEqual(self.record(), UUID(int=4))
        self.cursor.fetchone.side_effect = [(self.finding,), None, original]
        with self.assertRaises(ValueError):
            self.record(decision="approved")

    def test_reject_invalid_reason_and_identity(self):
        for changes in ({"reason": "   "}, {"actor_id": str(self.actor)},
                        {"key": "short"}, {"decision": "pending"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.record(**changes)
        self.cursor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
