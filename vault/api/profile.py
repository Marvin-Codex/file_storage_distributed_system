"""User profile and password settings."""

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View


class ProfileView(View):
    """GET /profile/ — show account and department membership."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        return render(request, "vault/profile.html")


class PasswordChangeView(View):
    """GET/POST /profile/password/ — change the current password."""

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "vault/password_change.html", {"form": PasswordChangeForm(request.user)})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            return redirect("/profile/?password=changed")
        return render(request, "vault/password_change.html", {"form": form})
