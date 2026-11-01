from django.contrib import admin
from django.urls import path, include
from django.conf import settings

urlpatterns = []
if settings.ROLE == "master":
    urlpatterns += [path("admin/", admin.site.urls)]
    urlpatterns += [path("", include("vault.urls"))]
else:
    urlpatterns += [path("", include("node.urls"))]
