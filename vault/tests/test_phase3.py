import hashlib
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from node.storage import open_blob, write_blob
from vault.models import FileEntry, FileVersion, Replica, StorageNode
from vault.services.node_client import NodeUnavailableError
from vault.services.replication import upload_file


class StreamingStorageTests(TestCase):
    def test_write_blob_accepts_file_like_data_and_can_be_read_incrementally(self):
        blob_id = FileVersion._meta.pk.default()
        content = b"streamed content"

        with tempfile.TemporaryDirectory() as data_dir, override_settings(
            NODE_DATA_DIR=data_dir
        ):
            size, checksum = write_blob(blob_id, BytesIO(content))
            blob = open_blob(blob_id)
            try:
                self.assertEqual(size, len(content))
                self.assertEqual(checksum, hashlib.sha256(content).hexdigest())
                self.assertEqual(blob.read(), content)
            finally:
                if blob is not None:
                    blob.close()


class UploadFallbackTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="uploader",
            password="password",
        )
        department = Group.objects.create(name="Computing")
        self.user.groups.add(department)
        for number in (1, 2, 3):
            StorageNode.objects.create(
                name=f"node{number}",
                address=f"http://127.0.0.1:90{number}1",
                is_alive=True,
                capacity_bytes=1000,
            )

    @override_settings(REPLICATION_FACTOR=2)
    def test_upload_uses_another_eligible_node_after_failure(self):
        content = b"fallback content"
        successful_calls = []

        def put(node, blob_id, data):
            if node.name == "node1":
                raise NodeUnavailableError("node1 unavailable")
            successful_calls.append(node.name)
            return len(content), hashlib.sha256(content).hexdigest()

        with patch("vault.services.replication.put_blob", side_effect=put):
            result = upload_file(
                self.user,
                "/Computing/fallback.txt",
                BytesIO(content),
            )

        self.assertEqual(len(result["replicas"]), 2)
        self.assertEqual(successful_calls, ["node2", "node3"])


class DeleteFileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="password",
        )
        department = Group.objects.create(name="Computing")
        self.user.groups.add(department)
        entry = FileEntry.objects.create(
            path="/Computing/delete.txt",
            owner=self.user,
            department=department,
        )
        version = FileVersion.objects.create(
            entry=entry,
            number=1,
            size=4,
            sha256=hashlib.sha256(b"data").hexdigest(),
            replication_factor=2,
        )
        for number in (1, 2):
            node = StorageNode.objects.create(
                name=f"node{number}",
                address=f"http://127.0.0.1:90{number}1",
                is_alive=True,
            )
            Replica.objects.create(version=version, node=node)

    def test_delete_removes_metadata_after_all_replicas_confirm(self):
        with patch("vault.services.replication.delete_blob") as delete_blob:
            response = self.client.delete(
                "/api/files/delete/?path=/Computing/delete.txt",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 401)
        self.client.force_login(self.user)
        with patch("vault.services.replication.delete_blob") as delete_blob:
            response = self.client.delete(
                "/api/files/delete/?path=/Computing/delete.txt",
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(FileEntry.objects.filter(path="/Computing/delete.txt").exists())
        self.assertEqual(delete_blob.call_count, 2)

    def test_delete_keeps_metadata_when_a_replica_cannot_be_confirmed(self):
        def delete(node, blob_id):
            if node.name == "node2":
                raise NodeUnavailableError("node2 unavailable")

        self.client.force_login(self.user)
        with patch("vault.services.replication.delete_blob", side_effect=delete):
            response = self.client.delete(
                "/api/files/delete/?path=/Computing/delete.txt",
            )

        self.assertEqual(response.status_code, 503)
        self.assertTrue(FileEntry.objects.filter(path="/Computing/delete.txt").exists())
