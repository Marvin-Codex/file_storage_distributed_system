from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from vault.models import FileEntry, FileVersion, Replica, StorageNode


class DashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="staff", password="password", is_staff=True
        )
        self.user = user_model.objects.create_user(
            username="user", password="password"
        )
        department = Group.objects.create(name="Computing")
        entry = FileEntry.objects.create(
            path="/Computing/notes.pdf",
            owner=self.staff,
            department=department,
        )
        version = FileVersion.objects.create(
            entry=entry,
            number=1,
            size=10,
            sha256="a" * 64,
            replication_factor=2,
        )
        alive_node = StorageNode.objects.create(
            name="node1",
            address="http://127.0.0.1:9001",
            is_alive=True,
            capacity_bytes=100,
            used_bytes=10,
        )
        dead_node = StorageNode.objects.create(
            name="node2",
            address="http://127.0.0.1:9002",
            is_alive=False,
            capacity_bytes=100,
            used_bytes=20,
        )
        Replica.objects.create(version=version, node=alive_node)
        Replica.objects.create(version=version, node=dead_node)

    def test_cluster_status_requires_staff(self):
        self.client.force_login(self.user)

        response = self.client.get("/api/cluster/status/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "permission_denied")

    def test_cluster_status_reports_nodes_and_under_replication(self):
        self.client.force_login(self.staff)

        response = self.client.get("/api/cluster/status/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["nodes"][0]["free_bytes"], 90)
        self.assertEqual(payload["files"][0]["path"], "/Computing/notes.pdf")
        self.assertTrue(payload["files"][0]["under_replicated"])
        self.assertEqual(payload["under_replicated"][0]["replicas"][0]["node"], "node1")

    def test_dashboard_renders_for_staff(self):
        self.client.force_login(self.staff)

        response = self.client.get("/dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/Computing/notes.pdf")
        self.assertContains(response, "Under-replicated")
