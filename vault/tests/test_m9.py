import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TransactionTestCase

from vault.models import FileEntry, FileVersion, StorageNode
from vault.services.replication import upload_file


class ConcurrentUploadTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("concurrency test requires PostgreSQL row locking")
        self.user = get_user_model().objects.create_user(
            username="uploader", password="password"
        )
        department = Group.objects.create(name="Computing")
        self.user.groups.add(department)
        for number in (1, 2):
            StorageNode.objects.create(
                name=f"node{number}",
                address=f"http://127.0.0.1:90{number}1",
                is_alive=True,
                capacity_bytes=1_000_000,
            )

    def test_concurrent_uploads_allocate_distinct_versions(self):
        def put_blob(node, blob_id, data):
            return len(data), hashlib.sha256(data).hexdigest()

        def upload():
            return upload_file(
                self.user, "/Computing/notes.pdf", BytesIO(b"data")
            )

        with patch(
            "vault.services.replication.put_blob", side_effect=put_blob
        ), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: upload(), range(2)))

        self.assertEqual({result["version"] for result in results}, {1, 2})
        self.assertEqual(
            FileVersion.objects.filter(
                entry__path="/Computing/notes.pdf"
            ).count(),
            2,
        )
        self.assertEqual(
            FileEntry.objects.get(path="/Computing/notes.pdf").versions.count(),
            2,
        )
