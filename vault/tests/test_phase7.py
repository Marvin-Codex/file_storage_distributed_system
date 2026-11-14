from django.contrib.auth import get_user_model
from django.test import TestCase


class FrontendRecoveryControlsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staff-user",
            password="password",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_workspace_exposes_delete_control(self):
        response = self.client.get("/files/")

        self.assertContains(response, "class=\"delete-button")
