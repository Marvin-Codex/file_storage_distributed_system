from django.urls import path, include
from .api.views import HeartbeatView

app_name = "vault"

urlpatterns = [
    path("internal/heartbeat/", HeartbeatView.as_view(), name="heartbeat"),
    path("api/", include("vault.api.urls")),
]
