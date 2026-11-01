from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from vault.models import FileEntry, StorageNode


class UiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member", password="password"
        )
        department = Group.objects.create(name="Computing")
        self.user.groups.add(department)
        FileEntry.objects.create(
            path="/Computing/one.txt",
            owner=self.user,
            department=department,
        )

    def test_workspace_redirects_anonymous_users_to_login(self):
        response = self.client.get("/files/")

        self.assertRedirects(response, "/login/?next=/files/")

    def test_profile_and_password_pages_require_login(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get("/profile/").status_code, 200)
        self.assertEqual(self.client.get("/profile/password/").status_code, 200)

    def test_file_list_has_pagination_metadata(self):
        self.client.force_login(self.user)

        response = self.client.get("/api/files/?page=1&page_size=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pagination"]["total"], 1)
        self.assertEqual(response.json()["pagination"]["pages"], 1)

    def test_staff_can_manage_departments_and_users(self):
        manager = get_user_model().objects.create_user(
            username="manager", password="manager-pass", is_staff=True
        )
        self.client.force_login(manager)

        response = self.client.post(
            "/manage/departments/new/",
            {"name": "Finance"},
        )
        self.assertRedirects(response, "/manage/")
        department = Group.objects.get(name="Finance")

        response = self.client.post(
            "/manage/users/new/",
            {
                "username": "finance-user",
                "email": "finance@example.com",
                "password": "finance-pass",
                "departments": [department.pk],
            },
        )
        self.assertRedirects(response, "/manage/")
        created = get_user_model().objects.get(username="finance-user")
        self.assertTrue(created.groups.filter(pk=department.pk).exists())
        self.assertTrue(self.client.get("/manage/").status_code, 200)

    def test_non_staff_cannot_use_management_console(self):
        self.client.force_login(self.user)

        response = self.client.get("/manage/")

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Access denied", response.content)

    def test_staff_can_register_node_and_get_setup_commands(self):
        manager = get_user_model().objects.create_user(
            username="node-manager", password="manager-pass", is_staff=True
        )
        self.client.force_login(manager)

        response = self.client.post(
            "/manage/nodes/new/",
            {
                "name": "node1",
                "address": "http://127.0.0.1:9001",
                "capacity_bytes": 10737418240,
                "data_dir": r".\data\node1",
                "master_url": "http://127.0.0.1:8000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(StorageNode.objects.filter(name="node1").exists())
        self.assertContains(response, "run_heartbeat")
        self.assertContains(response, "ROLE")
        self.assertContains(response, "controller")
        self.assertContains(response, "same value as the master")
        self.assertContains(response, r".\data\node1")

    def test_node_form_has_working_defaults_and_input_types(self):
        manager = get_user_model().objects.create_user(
            username="node-form-manager", password="manager-pass", is_staff=True
        )
        self.client.force_login(manager)

        response = self.client.get("/manage/nodes/new/")

        self.assertContains(response, 'value="node1"')
        self.assertContains(response, 'value="http://127.0.0.1:9001"')
        self.assertContains(response, 'value="10737418240"')
        self.assertContains(response, r'value=".\data\node1"')
        self.assertContains(response, 'value="http://127.0.0.1:8000"')
        self.assertContains(response, 'type="url"')
        self.assertContains(response, 'type="number"')

    def test_node_form_explains_invalid_values(self):
        manager = get_user_model().objects.create_user(
            username="node-error-manager", password="manager-pass", is_staff=True
        )
        self.client.force_login(manager)

        response = self.client.post(
            "/manage/nodes/new/",
            {
                "name": "node1",
                "address": "127.0.0.1",
                "capacity_bytes": "0",
                "data_dir": "",
                "master_url": "not-a-url",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not create this node yet.")
        self.assertContains(response, "Include a port in the address")
        self.assertContains(response, "Capacity must be greater than zero")
        self.assertContains(response, "Enter a folder path")

    def test_readiness_endpoint_reports_local_development_primary(self):
        response = self.client.get("/ready/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
