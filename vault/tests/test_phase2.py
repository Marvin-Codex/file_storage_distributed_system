import json

from django.conf import settings
from django.core import signing
from django.test import TestCase

from vault.models import StorageNode


class HeartbeatAuthenticationTests(TestCase):
    def _token(self, name):
        return signing.dumps(
            {"role": "node", "name": name},
            key=settings.CLUSTER_SECRET,
        )

    def _post(self, token_name, payload):
        return self.client.post(
            "/internal/heartbeat/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._token(token_name)}",
        )

    def test_heartbeat_requires_token_identity_to_match_payload(self):
        response = self._post(
            "node1",
            {
                "name": "node2",
                "address": "http://127.0.0.1:9002",
                "capacity_bytes": 100,
                "used_bytes": 10,
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(StorageNode.objects.exists())

    def test_heartbeat_rejects_invalid_capacity(self):
        response = self._post(
            "node1",
            {
                "name": "node1",
                "address": "http://127.0.0.1:9001",
                "capacity_bytes": 10,
                "used_bytes": 11,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(StorageNode.objects.exists())

    def test_heartbeat_registers_valid_node(self):
        response = self._post(
            "node1",
            {
                "name": "node1",
                "address": "http://127.0.0.1:9001",
                "capacity_bytes": 100,
                "used_bytes": 10,
            },
        )

        self.assertEqual(response.status_code, 200)
        node = StorageNode.objects.get(name="node1")
        self.assertEqual(node.address, "http://127.0.0.1:9001")
        self.assertTrue(node.is_alive)
