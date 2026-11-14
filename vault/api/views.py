"""Master API views."""

import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated

from ..models import StorageNode
from ..services.replication import (
    AllReplicasUnavailableError,
    DeleteError,
    DownloadError,
    FileNotFoundError,
    IntegrityFailedError,
    InvalidPathError,
    NotEnoughNodesUploadError,
    PermissionDeniedError,
    TooLargeError,
    UploadError,
    check_read_permission,
    delete_file,
    download_file,
    upload_file,
    validate_path,
    validate_prefix,
)
from .permissions import IsDepartmentMember, permission_error

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
            payload = None
        if payload is None or payload.get("role") != "node":
            logger.warning("Heartbeat token is invalid or has the wrong role")
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
        if payload.get("name") != name:
            logger.warning("Heartbeat token identity does not match node %s", name)
            return HttpResponse(status=401)

        if not isinstance(name, str) or len(name) > 64:
            return HttpResponseBadRequest("invalid node name")
        parsed_address = urlsplit(address) if isinstance(address, str) else None
        if (
            parsed_address is None
            or parsed_address.scheme not in {"http", "https"}
            or not parsed_address.netloc
            or parsed_address.path not in {"", "/"}
            or parsed_address.query
            or parsed_address.fragment
        ):
            return HttpResponseBadRequest("invalid node address")

        if (
            isinstance(capacity_bytes, bool)
            or isinstance(used_bytes, bool)
            or not isinstance(capacity_bytes, int)
            or not isinstance(used_bytes, int)
            or capacity_bytes < 0
            or used_bytes < 0
            or used_bytes > capacity_bytes
        ):
            return HttpResponseBadRequest("invalid node capacity")

        existing_node = StorageNode.objects.filter(name=name).first()
        needs_reconciliation = (
            existing_node is None
            or not existing_node.is_alive
            or existing_node.reconciliation_required
        )
        # update_or_create — never read-modify-write in Python (§12)
        StorageNode.objects.update_or_create(
            name=name,
            defaults={
                "address": address,
                "last_heartbeat": timezone.now(),
                "is_alive": True,
                "capacity_bytes": capacity_bytes,
                "used_bytes": used_bytes,
                "reconciliation_required": needs_reconciliation,
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
        error = permission_error(request, self, (IsAuthenticated,))
        if error:
            return error

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
        error = permission_error(request, self, (IsDepartmentMember,))
        if error:
            return error

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
        path = request.GET.get("path", "")
        version_str = request.GET.get("version", "")

        if not path:
            return JsonResponse(
                {"error": "invalid_path", "detail": "path is required"},
                status=400,
            )
        error = permission_error(request, self, (IsDepartmentMember,))
        if error:
            return error

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

        from django.http import FileResponse

        response = FileResponse(data, content_type="application/octet-stream")
        response["X-File-Version"] = str(version.number)
        response["X-File-SHA256"] = version.sha256
        response["X-Served-By"] = node_name
        return response


@method_decorator(csrf_exempt, name="dispatch")
class FileDeleteView(View):
    """DELETE /api/files/delete/?path=..."""

    def delete(self, request):
        path = request.GET.get("path", "")
        if not path:
            return JsonResponse(
                {"error": "invalid_path", "detail": "path is required"},
                status=400,
            )
        error = permission_error(request, self, (IsDepartmentMember,))
        if error:
            return error

        try:
            result = delete_file(request.user, path)
        except InvalidPathError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        except PermissionDeniedError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=403)
        except FileNotFoundError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=404)
        except DeleteError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=503)
        except UploadError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)

        return JsonResponse(result, status=200)

@method_decorator(csrf_exempt, name="dispatch")
class FileListView(View):
    """GET /api/files/?prefix=/Computing/

    Lists entries the user may see.
    """

    def get(self, request):
        error = permission_error(request, self, (IsAuthenticated,))
        if error:
            return error

        prefix = request.GET.get("prefix", "")
        normalized_prefix = ""
        if prefix:
            try:
                normalized_prefix, department = validate_prefix(prefix)
                check_read_permission(request.user, department)
            except InvalidPathError as exc:
                return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
            except PermissionDeniedError as exc:
                return JsonResponse({"error": exc.code, "detail": exc.detail}, status=403)
            error = permission_error(request, self, (IsDepartmentMember,))
            if error:
                return error

        from ..models import FileEntry
        if request.user.is_superuser:
            entries = FileEntry.objects.all()
        else:
            entries = FileEntry.objects.filter(
                department__in=request.user.groups.all()
            )

        if normalized_prefix:
            entries = entries.filter(path__startswith=normalized_prefix)

        try:
            page_number = max(int(request.GET.get("page", "1")), 1)
            page_size = min(max(int(request.GET.get("page_size", "20")), 1), 100)
        except ValueError:
            return JsonResponse(
                {"error": "invalid_path", "detail": "page and page_size must be integers"},
                status=400,
            )

        paginator = Paginator(entries.order_by("path"), page_size)
        try:
            page = paginator.page(page_number)
        except EmptyPage:
            page = paginator.page(paginator.num_pages or 1)

        results = []
        for e in page.object_list:
            latest = e.versions.order_by("-number").first()
            results.append({
                "path": e.path,
                "owner": e.owner.username,
                "department": e.department.name,
                "created_at": e.created_at.isoformat(),
                "latest_version": latest.number if latest else None,
            })

        return JsonResponse({
            "results": results,
            "pagination": {
                "page": page.number,
                "page_size": page_size,
                "pages": paginator.num_pages,
                "total": paginator.count,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        }, status=200)


@method_decorator(csrf_exempt, name="dispatch")
class FileVersionsView(View):
    """GET /api/files/versions/?path=...

    Lists versions of a path.
    """

    def get(self, request):
        path = request.GET.get("path", "")
        try:
            normalized_path, _ = validate_path(path)
        except InvalidPathError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=400)
        error = permission_error(request, self, (IsDepartmentMember,))
        if error:
            return error

        from ..models import FileEntry

        try:
            entry = FileEntry.objects.get(path=normalized_path)
        except FileEntry.DoesNotExist:
            return JsonResponse(
                {"error": "not_found", "detail": f"path '{path}' not found"},
                status=404,
            )

        try:
            check_read_permission(request.user, entry.department)
        except PermissionDeniedError as exc:
            return JsonResponse({"error": exc.code, "detail": exc.detail}, status=403)

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

        return JsonResponse({"path": normalized_path, "versions": versions}, status=200)
