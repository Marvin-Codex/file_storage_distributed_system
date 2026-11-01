"""Master API views."""

import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.contrib.auth.middleware import AuthenticationMiddleware

from ..models import StorageNode
from ..services.replication import (
    upload_file,
    download_file,
    UploadError,
    DownloadError,
    InvalidPathError,
    NotEnoughNodesUploadError,
    TooLargeError,
    PermissionDeniedError,
    FileNotFoundError,
    AllReplicasUnavailableError,
    IntegrityFailedError,
)

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class HeartbeatView(View):
    """POST /internal/heartbeat/

    Authenticated by signed node token (role="node"), not user auth.
    Master does update_or_create on StorageNode by name.
    """

    def post(self, request):
        # Authenticate via signed token
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return HttpResponse(status=401)
        token = auth[len("Bearer "):]
        try:
            payload = signing.loads(token, key=settings.CLUSTER_SECRET, max_age=60)
        except (signing.SignatureExpired, signing.BadSignature):
            logger.warning("Invalid heartbeat token signature")
            return HttpResponse(status=401)
        if payload.get("role") != "node":
            logger.warning("Heartbeat token has wrong role: %s", payload.get("role"))
            return HttpResponse(status=401)

        # Parse body
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return HttpResponseBadRequest("invalid json")

        name = data.get("name")
        address = data.get("address")
        capacity_bytes = data.get("capacity_bytes", 0)
        used_bytes = data.get("used_bytes", 0)

        if not name or not address:
            return HttpResponseBadRequest("missing name or address")

        # update_or_create — never read-modify-write in Python (§12)
        StorageNode.objects.update_or_create(
            name=name,
            defaults={
                "address": address,
                "last_heartbeat": timezone.now(),
                "is_alive": True,
                "capacity_bytes": capacity_bytes,
                "used_bytes": used_bytes,
            },
        )
        logger.debug("Heartbeat from %s (%s)", name, address)
        return HttpResponse(status=200)
@method_decorator(csrf_exempt, name="dispatch")
class FileUploadView(View):
    """POST /api/files/upload/

    Multipart: path, file. Creates entry (if new) and version N+1.
    Requires user authentication; user must be in the target department.
    """

    def post(self, request):
        if not request.user or not request.user.is_authenticated:
            return JsonResponse(
                {"error": "permission_denied", "detail": "authentication required"},
                status=401,
            )

        path = request.POST.get("path", "")
        uploaded_file = request.FILES.get("file")

        if not path:
            return JsonResponse(
                {"error": "invalid_path", "detail": "path is required"},
                status=400,
            )
        if not uploaded_file:
            return JsonResponse(
                {"error": "invalid_path", "detail": "file is required"},
                status=400,
            )

        try:
            result = upload_file(request.user, path, uploaded_file.file)
        except InvalidPathError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except PermissionDeniedError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=403)
        except TooLargeError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except NotEnoughNodesUploadError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except UploadError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except Exception:
            logger.exception("Unexpected upload error")
            return JsonResponse(
                {"error": "integrity_failed", "detail": "upload failed"},
                status=500,
            )

        return JsonResponse(result, status=201)

@method_decorator(csrf_exempt, name="dispatch")
class FileDownloadView(View):
    """GET /api/files/download/?path=...

    Streams the latest version. Optional &version=N.
    Tries replicas in order, verifies SHA-256, fails over on mismatch.
    """

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return JsonResponse(
                {"error": "permission_denied", "detail": "authentication required"},
                status=401,
            )

        path = request.GET.get("path", "")
        version_str = request.GET.get("version", "")

        if not path:
            return JsonResponse(
                {"error": "invalid_path", "detail": "path is required"},
                status=400,
            )

        version_number = None
        if version_str:
            try:
                version_number = int(version_str)
            except ValueError:
                return JsonResponse(
                    {"error": "invalid_path", "detail": "version must be an integer"},
                    status=400,
                )

        try:
            version, data, node_name = download_file(
                request.user, path, version_number
            )
        except InvalidPathError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except PermissionDeniedError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=403)
        except FileNotFoundError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=404)
        except AllReplicasUnavailableError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=503)
        except IntegrityFailedError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=500)
        except DownloadError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=500)
        except Exception:
            logger.exception("Unexpected download error")
            return JsonResponse(
                {"error": "integrity_failed", "detail": "download failed"},
                status=500,
            )

        response = HttpResponse(data, content_type="application/octet-stream")
        response["X-File-Version"] = str(version.number)
        response["X-File-SHA256"] = version.sha256
        response["X-Served-By"] = node_name
        return response

@method_decorator(csrf_exempt, name="dispatch")
class FileListView(View):
    """GET /api/files/?prefix=/Computing/

    Lists entries the user may see.
    """

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return JsonResponse(
                {"error": "permission_denied", "detail": "authentication required"},
                status=401,
            )

        prefix = request.GET.get("prefix", "")

        if prefix and not prefix.startswith("/"):
            return JsonResponse(
                {"error": "invalid_path", "detail": "prefix must start with '/'"},
                status=400,
            )

        from ..models import FileEntry
        if request.user.is_superuser:
            entries = FileEntry.objects.all()
        else:
            entries = FileEntry.objects.filter(
                department__in=request.user.groups.all()
            )

        if prefix:
            entries = entries.filter(path__startswith=prefix)

        results = []
        for e in entries.order_by("path"):
            latest = e.versions.order_by("-number").first()
            results.append({
                "path": e.path,
                "owner": e.owner.username,
                "department": e.department.name,
                "created_at": e.created_at.isoformat(),
                "latest_version": latest.number if latest else None,
            })

        return JsonResponse({"results": results}, status=200)


@method_decorator(csrf_exempt, name="dispatch")
class FileVersionsView(View):
    """GET /api/files/versions/?path=...

    Lists versions of a path.
    """

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return JsonResponse(
                {"error": "permission_denied", "detail": "authentication required"},
                status=401,
            )

        path = request.GET.get("path", "")
        if not path:
            return JsonResponse(
                {"error": "invalid_path", "detail": "path is required"},
                status=400,
            )

        from ..models import FileEntry

        try:
            entry = FileEntry.objects.get(path=path)
        except FileEntry.DoesNotExist:
            return JsonResponse(
                {"error": "not_found", "detail": f"path '{path}' not found"},
                status=404,
            )

        if not request.user.is_superuser:
            if not request.user.groups.filter(pk=entry.department.pk).exists():
                return JsonResponse(
                    {"error": "permission_denied", "detail": "not in department"},
                    status=403,
                )

        versions = []
        for v in entry.versions.order_by("-number"):
            versions.append({
                "number": v.number,
                "size": v.size,
                "sha256": v.sha256,
                "created_at": v.created_at.isoformat(),
                "replication_factor": v.replication_factor,
                "replica_count": v.replicas.filter(node__is_alive=True).count(),
            })

        return JsonResponse({"path": path, "versions": versions}, status=200)
