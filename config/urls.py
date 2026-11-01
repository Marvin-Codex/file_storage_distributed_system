from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = []
if settings.ROLE in {"master", "controller"}:
    urlpatterns += [path("admin/", admin.site.urls)]
    urlpatterns += [path("", include("vault.urls"))]
if settings.ROLE in {"node", "controller"}:
    urlpatterns += [path("", include("node.urls"))]
