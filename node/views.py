"""Storage node views: PUT/GET/DELETE /store/<uuid>, GET /health."""

import json
import uuid

from django.conf import settings
from django.core import signing
from django.http import FileResponse, HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .storage import delete_blob, free_space, list_blob_ids, open_blob, write_blob


def _authenticate(request: HttpRequest) -> bool:
    """Check Authorization: Bearer <signed token> header.
    Token must be a valid master-signed token, max age 60 s.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[len("Bearer "):]
    try:
        payload = signing.loads(token, key=settings.CLUSTER_SECRET, max_age=60)
    except (signing.SignatureExpired, signing.BadSignature):
        return False
    return payload.get("role") == "master"


@method_decorator(csrf_exempt, name="dispatch")
class StoreView(View):
    """PUT/GET/DELETE /store/<uuid>

    Nodes are deliberately dumb: they store and serve opaque blobs by UUID.
    They know nothing about users, paths, or versions.
    """

    def put(self, request: HttpRequest, blob_id: uuid.UUID) -> HttpResponse:
        if not _authenticate(request):
            return HttpResponse(status=401)
        size, sha256 = write_blob(blob_id, request)
        body = json.dumps({"size": size, "sha256": sha256})
        return HttpResponse(body, status=201, content_type="application/json")

    def get(self, request: HttpRequest, blob_id: uuid.UUID) -> HttpResponse:
        if not _authenticate(request):
            return HttpResponse(status=401)
        blob = open_blob(blob_id)
        if blob is None:
            return HttpResponse(status=404)
        return FileResponse(blob, content_type="application/octet-stream")

    def delete(self, request: HttpRequest, blob_id: uuid.UUID) -> HttpResponse:
        if not _authenticate(request):
            return HttpResponse(status=401)
        delete_blob(blob_id)
        return HttpResponse(status=204)


class HealthView(View):
    """GET /health — returns free space."""

    def get(self, request: HttpRequest) -> HttpResponse:
        body = json.dumps({"free_bytes": free_space()})
        return HttpResponse(body, status=200, content_type="application/json")


class InventoryView(View):
    """GET /inventory/ — return opaque blob IDs for master reconciliation."""

    def get(self, request: HttpRequest) -> HttpResponse:
        if not _authenticate(request):
            return HttpResponse(status=401)
        body = json.dumps({"blobs": sorted(str(blob_id) for blob_id in list_blob_ids())})
        return HttpResponse(body, status=200, content_type="application/json")