"""DRF permission classes for the master API."""

from django.http import JsonResponse
from rest_framework import permissions


class IsDepartmentMember(permissions.BasePermission):
    """User must be a member of the department matching the first path segment."""

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        data = getattr(request, "data", request.POST)
        query_params = getattr(request, "query_params", request.GET)
        if request.method in {"POST", "PUT", "PATCH"}:
            path = data.get("path", "")
        else:
            path = query_params.get("path") or query_params.get("prefix", "")
        if path:
            first_segment = path.strip("/").split("/")[0] if path.strip("/") else ""
            if first_segment:
                return request.user.groups.filter(name=first_segment).exists()
        return request.method in permissions.SAFE_METHODS


def permission_error(request, view, permission_classes) -> JsonResponse | None:
    """Apply DRF permissions while preserving the API error contract."""
    for permission_class in permission_classes:
        permission = permission_class()
        if permission.has_permission(request, view):
            continue
        if not request.user or not request.user.is_authenticated:
            return JsonResponse(
                {"error": "permission_denied", "detail": "authentication required"},
                status=401,
            )
        return JsonResponse(
            {"error": "permission_denied", "detail": "department access required"},
            status=403,
        )
    return None


class IsStaffOrReadOnly(permissions.BasePermission):
    """Staff can write; any authenticated user can read."""

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_staff


class IsStaff(permissions.BasePermission):
    """Only authenticated staff users may access a staff-only endpoint."""

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )