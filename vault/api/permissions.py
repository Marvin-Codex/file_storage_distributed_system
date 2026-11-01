"""DRF permission classes for the master API."""

from rest_framework import permissions


class IsDepartmentMember(permissions.BasePermission):
    """User must be a member of the department matching the first path segment."""

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        path = request.data.get("path", "") if request.method == "POST" else ""
        if path:
            first_segment = path.strip("/").split("/")[0] if path.strip("/") else ""
            if first_segment:
                return request.user.groups.filter(name=first_segment).exists()
        return True


class IsStaffOrReadOnly(permissions.BasePermission):
    """Staff can write; any authenticated user can read."""

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_staff