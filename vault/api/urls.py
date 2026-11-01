"""Master API URLs — endpoints under /api/ (M4–M7 populate these)."""

from django.urls import path
from .views import FileUploadView, FileDownloadView, FileListView, FileVersionsView

app_name = "vault_api"

urlpatterns = [
    path("files/upload/", FileUploadView.as_view(), name="file_upload"),
    path("files/download/", FileDownloadView.as_view(), name="file_download"),
    path("files/", FileListView.as_view(), name="file_list"),
    path("files/versions/", FileVersionsView.as_view(), name="file_versions"),
]