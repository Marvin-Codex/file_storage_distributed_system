import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from vault.models import EnrollmentToken, StorageNode
from vault.services.tokens import (
    hash_enrollment_token,
    make_enrollment_token,
)


class EnrollmentFlowTests(TestCase):
    def test_valid_token_registers_node_and_credential_authenticates_heartbeat(self):
        raw_token = make_enrollment_token()
        EnrollmentToken.objects.create(
            token_hash=hash_enrollment_token(raw_token),
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post(
            "/internal/enroll/",
            data=json.dumps(
                {
                    "token": raw_token,
                    "name": "node1",
                    "address": "http://127.0.0.1:9001",
                    "capacity_bytes": 1000,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        credential = response.json()["credential"]
        heartbeat = self.client.post(
            "/internal/heartbeat/",
            data=json.dumps(
                {
                    "name": "node1",
                    "address": "http://127.0.0.1:9001",
                    "capacity_bytes": 1000,
                    "used_bytes": 0,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {credential}",
        )

        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(StorageNode.objects.get(name="node1").is_alive)

    def test_enrollment_token_is_single_use(self):
        raw_token = make_enrollment_token()
        EnrollmentToken.objects.create(
            token_hash=hash_enrollment_token(raw_token),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        payload = {
            "token": raw_token,
            "name": "node1",
            "address": "http://127.0.0.1:9001",
            "capacity_bytes": 1000,
        }

        first = self.client.post(
            "/internal/enroll/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        payload["name"] = "node2"
        payload["address"] = "http://127.0.0.1:9002"
        second = self.client.post(
            "/internal/enroll/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 401)

    def test_expired_enrollment_token_is_rejected(self):
        raw_token = make_enrollment_token()
        EnrollmentToken.objects.create(
            token_hash=hash_enrollment_token(raw_token),
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.post(
            "/internal/enroll/",
            data=json.dumps(
                {
                    "token": raw_token,
                    "name": "node1",
                    "address": "http://127.0.0.1:9001",
                    "capacity_bytes": 1000,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(StorageNode.objects.exists())

    def test_management_command_creates_hashed_token(self):
        output = StringIO()

        call_command("create_enrollment_token", expires_in=60, stdout=output)

        raw_token = output.getvalue().strip()
        self.assertTrue(raw_token)
        self.assertTrue(
            EnrollmentToken.objects.filter(
                token_hash=hash_enrollment_token(raw_token)
            ).exists()
        )

    @patch("vault.management.commands.join_cluster._session.post")
    def test_join_command_does_not_log_enrollment_token(self, post):
        post.return_value.status_code = 201
        post.return_value.json.return_value = {"credential": "node-credential"}
        output = StringIO()

        call_command(
            "join_cluster",
            master="http://127.0.0.1:8000",
            token="one-time-token",
            name="node1",
            address="http://127.0.0.1:9001",
            capacity_bytes=1000,
            stdout=output,
        )

        self.assertNotIn("one-time-token", output.getvalue())
        self.assertIn("NODE_CREDENTIAL=node-credential", output.getvalue())
