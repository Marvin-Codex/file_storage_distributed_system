"""Health endpoints used by DNS or a reverse proxy during master failover."""

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views import View


class ReadinessView(View):
    """Return ready only when this controller serves the PostgreSQL primary."""

    def get(self, request: HttpRequest) -> JsonResponse:
        if settings.HA_ENABLED and connection.vendor != "postgresql":
            return JsonResponse(
                {"ready": False, "reason": "postgresql_required"},
                status=503,
            )
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_is_in_recovery()")
                in_recovery = bool(cursor.fetchone()[0])
            if in_recovery:
                return JsonResponse(
                    {"ready": False, "role": "replica"},
                    status=503,
                )
        return JsonResponse(
            {
                "ready": True,
                "role": "primary",
                "control_plane": settings.CONTROL_PLANE_DNS,
            }
        )
