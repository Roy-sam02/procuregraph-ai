import hashlib
import json
import os
import secrets
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app


class ReviewDecisionApiTests(unittest.TestCase):
    def setUp(self):
        self.tenant, self.actor, self.finding = (str(UUID(int=n)) for n in (1, 2, 3))
        self.token, self.shared = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
               "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.shared,
               "PROCUREGRAPH_DEMO_REVIEWER": json.dumps({
                   "tenant_id": self.tenant, "reviewer_id": self.actor,
                   "token_sha256": hashlib.sha256(self.token.encode()).hexdigest(),
               }), "PROCUREGRAPH_DB_PORT": "5432", "PROCUREGRAPH_DB_PASSWORD": "local-test"}
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.connect = self.enterContext(patch("apps.api.app.main.psycopg.connect"))
        self.record = self.enterContext(patch("apps.api.app.main.record_approval"))
        self.client = self.enterContext(TestClient(app))
        self.path = f"/api/v1/review/findings/{self.finding}/decision"
        self.body = {"tenant_id": self.tenant, "decision": "rejected",
                     "reason": " Checked the contract "}
        self.headers = {"Authorization": f"Bearer {self.token}",
                        "Idempotency-Key": "local-decision-0001"}

    def test_identity_is_server_supplied_and_retry_key_reaches_storage(self):
        self.record.return_value = UUID(int=4)
        result = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"id": str(UUID(int=4)), "finding_id": self.finding,
                                         "tenant_id": self.tenant, "actor_id": self.actor,
                                         "decision": "rejected"})
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertEqual(self.record.call_args.args[1:], (
            UUID(self.tenant), UUID(self.finding), UUID(self.actor),
            "rejected", "Checked the contract", "local-decision-0001",
        ))

    def test_denied_requests_never_connect_or_write(self):
        cases = [({"Idempotency-Key": "local-decision-0001"}, self.body, 401),
                 ({**self.headers, "Authorization": f"Bearer {self.shared}"}, self.body, 401),
                 (self.headers, {**self.body, "tenant_id": str(UUID(int=9))}, 403)]
        for headers, body, expected in cases:
            with self.subTest(expected=expected):
                result = self.client.post(self.path, json=body, headers=headers)
                self.assertEqual(result.status_code, expected)
        self.connect.assert_not_called()
        self.record.assert_not_called()

    def test_invalid_reason_and_key_rejected_without_storage(self):
        for body, headers in [({**self.body, "reason": "  "}, self.headers),
                              (self.body, {"Authorization": f"Bearer {self.token}"})]:
            self.assertEqual(self.client.post(self.path, json=body, headers=headers).status_code, 422)
        self.connect.assert_not_called()

    def test_conflict_does_not_return_approval(self):
        self.record.side_effect = ValueError("Already decided")
        result = self.client.post(self.path, json=self.body, headers=self.headers)
        self.assertEqual(result.status_code, 409)
        self.assertNotIn("Already decided", result.text)


if __name__ == "__main__":
    unittest.main()
