from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from vault.services.replication import (
    InvalidPathError,
    PermissionDeniedError,
    check_read_permission,
    check_write_permission,
    validate_path,
    validate_prefix,
)


class PathValidationTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Computing")

    def test_normalizes_duplicate_slashes_and_requires_department(self):
        path, department = validate_path("//Computing//notes.pdf")

        self.assertEqual(path, "/Computing/notes.pdf")
        self.assertEqual(department, self.group)

    def test_rejects_traversal_null_and_control_characters(self):
        for path in ("/Computing/../secret", "/Computing/\x00secret", "/Computing/\tsecret"):
            with self.subTest(path=path), self.assertRaises(InvalidPathError):
                validate_path(path)

    def test_prefix_is_normalized_with_trailing_slash(self):
        prefix, department = validate_prefix("/Computing")

        self.assertEqual(prefix, "/Computing/")
        self.assertEqual(department, self.group)


class DepartmentPermissionTests(TestCase):
    def test_user_must_belong_to_department(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="user", password="password")
        group = Group.objects.create(name="Computing")
        other_group = Group.objects.create(name="Mathematics")
        user.groups.add(group)

        check_write_permission(user, group)
        check_read_permission(user, group)
        with self.assertRaises(PermissionDeniedError):
            check_write_permission(user, other_group)
        with self.assertRaises(PermissionDeniedError):
            check_read_permission(user, other_group)

    def test_api_permission_class_rejects_other_department(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="api-user", password="password")
        Group.objects.create(name="Computing")
        other_group = Group.objects.create(name="Mathematics")
        user.groups.add(other_group)
        client = Client()
        client.force_login(user)

        response = client.get("/api/files/?prefix=/Computing/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "permission_denied")
