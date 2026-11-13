from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from vault.models import EnrollmentToken, StorageNode
from vault.services.tokens import hash_enrollment_token


class FrontendRecoveryControlsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staff-user",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_enrollment_page_creates_single_use_token(self):
        response = self.client.post(
            "/manage/enrollment-token/",
            {"expires_in": 600},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Copy this token now")
        self.assertEqual(EnrollmentToken.objects.count(), 1)
        token = response.context["token"]
        enrollment = EnrollmentToken.objects.get()
        self.assertEqual(enrollment.token_hash, hash_enrollment_token(token))
        self.assertGreater(
            enrollment.expires_at,
            timezone.now() + timedelta(seconds=500),
        )

    def test_management_can_revoke_active_node_credential(self):
        node = StorageNode.objects.create(
            name="node1",
            address="http://127.0.0.1:9001",
            credential_hash="a" * 64,
        )

        response = self.client.post(f"/manage/nodes/{node.pk}/revoke/")

        self.assertRedirects(response, "/manage/")
        node.refresh_from_db()
        self.assertIsNotNone(node.credential_revoked_at)

    def test_workspace_exposes_delete_control(self):
        response = self.client.get("/files/")

        self.assertContains(response, "class=\"delete-button")
