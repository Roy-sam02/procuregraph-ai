import hashlib
import json
import os
import secrets
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app


class ReviewerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tenant = str(UUID(int=1))
        self.reviewer = str(UUID(int=2))
        self.other_tenant = str(UUID(int=3))
        self.token = secrets.token_urlsafe(32)
        self.shared_token = secrets.token_urlsafe(32)
        self.config = {
            "reviewer_id": self.reviewer,
            "tenant_id": self.tenant,
            "token_sha256": hashlib.sha256(self.token.encode("ascii")).hexdigest(),
        }
        env = {
            "PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
            "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.shared_token,
            "PROCUREGRAPH_DEMO_REVIEWER": json.dumps(self.config),
        }
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.connect = self.enterContext(patch("apps.api.app.main.psycopg.connect"))
        self.addCleanup(self.connect.assert_not_called)
        self.client = self.enterContext(TestClient(app))

    def request(self, *, tenant=None, authorization=None, **query):
        headers = {"Authorization": authorization} if authorization is not None else {}
        return self.client.get("/api/v1/review/me", headers=headers,
                               params={"tenant_id": tenant or self.tenant, **query})

    def test_identity_and_role_come_from_server_grant(self):
        response = self.request(authorization=f"bearer {self.token}",
                                reviewer_id=self.other_tenant, role="admin")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "reviewer_id": self.reviewer, "tenant_id": self.tenant, "role": "reviewer",
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_missing_malformed_wrong_and_shared_tokens_are_denied(self):
        for authorization in (None, "Bearer short", f"Basic {self.token}",
                              f"Bearer {secrets.token_urlsafe(32)}", f"Bearer {self.shared_token}"):
            with self.subTest(kind=authorization.split()[0] if authorization else "absent"):
                response = self.request(authorization=authorization)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_authenticated_reviewer_cannot_switch_tenant(self):
        self.assertEqual(self.request(tenant=self.other_tenant).status_code, 401)
        response = self.request(tenant=self.other_tenant, authorization=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("reviewer_id", response.json())

    def test_unconfigured_or_disabled_route_is_unavailable(self):
        os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "0"
        self.assertEqual(self.request().status_code, 404)
        os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "1"
        del os.environ["PROCUREGRAPH_DEMO_REVIEWER"]
        self.assertEqual(self.request().status_code, 404)

    def test_invalid_configuration_or_shared_credential_reuse_fails_closed(self):
        shared_digest = hashlib.sha256(self.shared_token.encode("ascii")).hexdigest()
        for config in ({**self.config, "token_sha256": "bad"},
                       {**self.config, "token_sha256": shared_digest}):
            os.environ["PROCUREGRAPH_DEMO_REVIEWER"] = json.dumps(config)
            response = self.request(authorization=f"Bearer {self.shared_token}")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(shared_digest, response.text)
