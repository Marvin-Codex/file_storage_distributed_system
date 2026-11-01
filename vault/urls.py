from django.contrib.auth import views as auth_views
from django.urls import include, path

from .api.dashboard import DashboardView
from .api.ha import ReadinessView
from .api.management import (
    DepartmentCreateView,
    DepartmentDeleteView,
    DepartmentUpdateView,
    ManagementView,
    NodeCreateView,
    UserCreateView,
    UserDeleteView,
    UserUpdateView,
)
from .api.portal import PortalView
from .api.profile import PasswordChangeView, ProfileView
from .api.views import HeartbeatView

app_name = "vault"

urlpatterns = [
    path("internal/heartbeat/", HeartbeatView.as_view(), name="heartbeat"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("ready/", ReadinessView.as_view(), name="readiness"),
    path("manage/", ManagementView.as_view(), name="management"),
    path("manage/nodes/new/", NodeCreateView.as_view(), name="node_create"),
    path("manage/departments/new/", DepartmentCreateView.as_view(), name="department_create"),
    path("manage/departments/<int:pk>/edit/", DepartmentUpdateView.as_view(), name="department_edit"),
    path("manage/departments/<int:pk>/delete/", DepartmentDeleteView.as_view(), name="department_delete"),
    path("manage/users/new/", UserCreateView.as_view(), name="user_create"),
    path("manage/users/<int:pk>/edit/", UserUpdateView.as_view(), name="user_edit"),
    path("manage/users/<int:pk>/delete/", UserDeleteView.as_view(), name="user_delete"),
    path("files/", PortalView.as_view(), name="portal"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/password/", PasswordChangeView.as_view(), name="password_change"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="vault/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", include("vault.api.urls")),
]
