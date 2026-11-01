"""Cluster status API and server-rendered dashboard."""

from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from ..models import FileEntry, StorageNode
from .permissions import IsStaff, permission_error


def _cluster_snapshot() -> dict[str, Any]:
    nodes = list(StorageNode.objects.order_by("name"))
    files = []
    under_replicated = []

    entries = FileEntry.objects.select_related("department").prefetch_related(
        "versions__replicas__node"
    ).order_by("path")
    for entry in entries:
        versions = list(entry.versions.all())
        if not versions:
            continue
        version = max(versions, key=lambda item: item.number)
        replicas = list(version.replicas.all())
        alive_replicas = [replica for replica in replicas if replica.node.is_alive]
        file_data = {
            "path": entry.path,
            "department": entry.department.name,
            "version": version.number,
            "size": version.size,
            "sha256": version.sha256,
            "replication_factor": version.replication_factor,
            "replicas": [
                {"node": replica.node.name, "is_alive": replica.node.is_alive}
                for replica in replicas
            ],
            "alive_replica_count": len(alive_replicas),
            "under_replicated": len(alive_replicas) < version.replication_factor,
        }
        files.append(file_data)
        if file_data["under_replicated"]:
            under_replicated.append(file_data)

    return {
        "nodes": [
            {
                "name": node.name,
                "address": node.address,
                "is_alive": node.is_alive,
                "last_heartbeat": node.last_heartbeat.isoformat()
                if node.last_heartbeat
                else None,
                "capacity_bytes": node.capacity_bytes,
                "used_bytes": node.used_bytes,
                "free_bytes": node.free_bytes,
            }
            for node in nodes
        ],
        "files": files,
        "under_replicated": under_replicated,
    }


class ClusterStatusView(View):
    """GET /api/cluster/status/ — staff-only cluster summary."""

    def get(self, request: HttpRequest) -> JsonResponse:
        error = permission_error(request, self, (IsStaff,))
        if error:
            return error
        return JsonResponse(_cluster_snapshot())


class DashboardView(View):
    """GET /dashboard/ — staff-only HTML cluster dashboard."""

    def get(self, request: HttpRequest) -> HttpResponse:
        error = permission_error(request, self, (IsStaff,))
        if error:
            return error
        snapshot = _cluster_snapshot()
        snapshot["node_count"] = len(snapshot["nodes"])
        snapshot["alive_node_count"] = sum(
            node["is_alive"] for node in snapshot["nodes"]
        )
        snapshot["file_count"] = len(snapshot["files"])
        snapshot["healthy_file_count"] = snapshot["file_count"] - len(
            snapshot["under_replicated"]
        )
        return render(request, "vault/dashboard.html", snapshot)
