"""Authenticated file workspace view."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View


class PortalView(View):
    """GET /files/ — authenticated user file workspace."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            from django.shortcuts import redirect

            return redirect(f"/login/?next={request.path}")
        return render(
            request,
            "vault/portal.html",
            {"department_names": list(request.user.groups.values_list("name", flat=True))},
        )
