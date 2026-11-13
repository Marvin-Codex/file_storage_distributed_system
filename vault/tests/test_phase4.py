import hashlib
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from vault.models import FileEntry, FileVersion, Replica, StorageNode
from vault.services.node_client import NodeUnavailableError
from vault.services.replication import trigger_self_healing


class ReplicaRepairTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="repair-user",
            password="password",
        )
        department = Group.objects.create(name="Computing")
        entry = FileEntry.objects.create(
            path="/Computing/repair.txt",
            owner=user,
            department=department,
        )
        self.content = b"repair content"
        self.version = FileVersion.objects.create(
            entry=entry,
            number=1,
            size=len(self.content),
            sha256=hashlib.sha256(self.content).hexdigest(),
            replication_factor=2,
        )

    def _node(self, name, alive=True):
        return StorageNode.objects.create(
            name=name,
            address=f"http://127.0.0.1:{9000 + int(name[-1])}",
            is_alive=alive,
            capacity_bytes=1000,
            used_bytes=0,
        )

    def test_repairs_missing_replica_on_another_eligible_node(self):
        source = self._node("node1")
        unavailable = self._node("node2", alive=False)
        target = self._node("node3")
        Replica.objects.create(
            version=self.version,
            node=source,
            verified_at=timezone.now(),
        )
        Replica.objects.create(
            version=self.version,
            node=unavailable,
            verified_at=timezone.now(),
        )

        with patch(
            "vault.services.replication.get_blob",
            return_value=BytesIO(self.content),
        ), patch(
            "vault.services.replication.put_blob",
            return_value=(len(self.content), self.version.sha256),
        ):
            summary = trigger_self_healing()

        self.assertEqual(summary["healed"], 1)
        self.assertTrue(
            Replica.objects.filter(version=self.version, node=target).exists()
        )

    def test_corrupt_replica_is_rewritten_without_creating_duplicate_row(self):
        corrupt = self._node("node1")
        source = self._node("node2")
        Replica.objects.create(
            version=self.version,
            node=corrupt,
            verified_at=None,
        )
        Replica.objects.create(
            version=self.version,
            node=source,
            verified_at=timezone.now(),
        )

        def get_blob(node, blob_id):
            return BytesIO(b"corrupt") if node == corrupt else BytesIO(self.content)

        with patch("vault.services.replication.get_blob", side_effect=get_blob), patch(
            "vault.services.replication.put_blob",
            return_value=(len(self.content), self.version.sha256),
        ):
            summary = trigger_self_healing()

        self.assertEqual(summary["healed"], 1)
        repaired = Replica.objects.get(version=self.version, node=corrupt)
        self.assertIsNotNone(repaired.verified_at)
        self.assertEqual(
            Replica.objects.filter(version=self.version, node=corrupt).count(),
            1,
        )

    def test_failed_repair_target_does_not_prevent_next_target(self):
        source = self._node("node1")
        failed_target = self._node("node2")
        successful_target = self._node("node3")
        Replica.objects.create(
            version=self.version,
            node=source,
            verified_at=timezone.now() - timedelta(seconds=1),
        )

        def put_blob(node, blob_id, data):
            if node == failed_target:
                raise NodeUnavailableError("target unavailable")
            return len(self.content), self.version.sha256

        with patch(
            "vault.services.replication.get_blob",
            return_value=BytesIO(self.content),
        ), patch(
            "vault.services.replication.put_blob",
            side_effect=put_blob,
        ):
            summary = trigger_self_healing()

        self.assertEqual(summary["healed"], 1)
        self.assertTrue(
            Replica.objects.filter(
                version=self.version,
                node=successful_target,
            ).exists()
        )
