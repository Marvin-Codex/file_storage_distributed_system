import hashlib
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.test import TestCase
from django.utils import timezone

from vault.models import FileEntry, FileVersion, Replica, StorageNode
from vault.services.node_client import NodeUnavailableError
from vault.services.reconciliation import (
    reconcile_node,
    reconcile_required_nodes,
)


class ReconciliationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="recovery-user",
            password="password",
        )
        department = Group.objects.create(name="Computing")
        entry = FileEntry.objects.create(
            path="/Computing/recovery.txt",
            owner=user,
            department=department,
        )
        version = FileVersion.objects.create(
            entry=entry,
            number=1,
            size=4,
            sha256=hashlib.sha256(b"data").hexdigest(),
            replication_factor=1,
        )
        self.node = StorageNode.objects.create(
            name="node1",
            address="http://127.0.0.1:9001",
            is_alive=True,
            reconciliation_required=True,
        )
        self.replica = Replica.objects.create(
            version=version,
            node=self.node,
            verified_at=timezone.now(),
        )

    def test_missing_inventory_blob_is_marked_unverified(self):
        with patch("vault.services.reconciliation.list_blob_ids", return_value=set()):
            result = reconcile_node(self.node)

        self.replica.refresh_from_db()
        self.node.refresh_from_db()
        self.assertEqual(result["missing"], 1)
        self.assertIsNone(self.replica.verified_at)
        self.assertFalse(self.node.reconciliation_required)
        self.assertIsNotNone(self.node.last_reconciled_at)

    def test_untracked_inventory_blob_is_preserved(self):
        orphan_id = uuid.uuid4()
        with patch(
            "vault.services.reconciliation.list_blob_ids",
            return_value={self.replica.version_id, orphan_id},
        ):
            result = reconcile_node(self.node)

        self.assertEqual(result["untracked"], 1)
        self.assertFalse(
            Replica.objects.filter(version_id=orphan_id, node=self.node).exists()
        )

    def test_unavailable_node_remains_reconciliation_required(self):
        with patch(
            "vault.services.reconciliation.list_blob_ids",
            side_effect=NodeUnavailableError("offline"),
        ):
            result = reconcile_required_nodes()

        self.node.refresh_from_db()
        self.assertEqual(result["failed"], 1)
        self.assertTrue(self.node.reconciliation_required)


class ReconnectHeartbeatTests(TestCase):
    def test_reconnect_marks_node_for_reconciliation(self):
        node = StorageNode.objects.create(
            name="node1",
            address="http://127.0.0.1:9001",
            is_alive=False,
            reconciliation_required=False,
            last_heartbeat=timezone.now() - timedelta(minutes=5),
        )
        token = signing.dumps(
            {"role": "node", "name": node.name},
            key=settings.CLUSTER_SECRET,
        )

        response = self.client.post(
            "/internal/heartbeat/",
            data=json.dumps(
                {
                    "name": node.name,
                    "address": node.address,
                    "capacity_bytes": 1000,
                    "used_bytes": 0,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        node.refresh_from_db()
        self.assertTrue(node.reconciliation_required)
