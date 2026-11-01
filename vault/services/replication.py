"""Upload orchestration — replicate a file to k nodes and record metadata."""

import hashlib
import logging
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import models, transaction
from django.utils import timezone

from ..models import FileEntry, FileVersion, Replica, StorageNode
from .node_client import NodeUnavailableError, delete_blob, get_blob, put_blob
from .placement import NotEnoughNodesError, choose_nodes

logger = logging.getLogger(__name__)
User = get_user_model()


class UploadError(Exception):
    """Base exception for upload failures."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class InvalidPathError(UploadError):
    def __init__(self, detail: str):
        super().__init__("invalid_path", detail)


class NotEnoughNodesUploadError(UploadError):
    def __init__(self, detail: str):
        super().__init__("not_enough_nodes", detail)


class TooLargeError(UploadError):
    def __init__(self, detail: str):
        super().__init__("too_large", detail)


class PermissionDeniedError(UploadError):
    def __init__(self, detail: str):
        super().__init__("permission_denied", detail)


def validate_path(path: str):
    """Validate and normalize a virtual path."""
    if not path:
        raise InvalidPathError("path is required")
    if not path.startswith("/"):
        raise InvalidPathError("path must start with '/'")
    if len(path) > 512:
        raise InvalidPathError("path exceeds 512 characters")
    if "\\" in path:
        raise InvalidPathError("path must not contain backslashes")
    if "\\x00" in path:
        raise InvalidPathError("path must not contain null bytes")
    for ch in path:
        if ord(ch) < 32 and ch not in "	":
            raise InvalidPathError("path contains control characters")
    while "//" in path:
        path = path.replace("//", "/")
    segments = [s for s in path.split("/") if s]
    if path.endswith("/") and path != "/":
        raise InvalidPathError("path must not end with a trailing slash")
    if not segments:
        raise InvalidPathError("path must have at least one segment")
    if ".." in segments:
        raise InvalidPathError("path must not contain '..' segments")
    first_segment = segments[0]
    try:
        department = Group.objects.get(name=first_segment)
    except Group.DoesNotExist:
        raise InvalidPathError(f"department '{first_segment}' does not exist")
    normalized = "/" + "/".join(segments)
    return normalized, department


def check_write_permission(user, department) -> None:
    """Check that user can write to the given department."""
    if user.is_superuser:
        return
    if not user.groups.filter(pk=department.pk).exists():
        raise PermissionDeniedError(
            f"user '{user.username}' is not in department '{department.name}'"
        )


def check_size(size: int) -> None:
    """Check that file size is within MAX_UPLOAD_BYTES."""
    if size > settings.MAX_UPLOAD_BYTES:
        raise TooLargeError(
            f"file size {size} exceeds max {settings.MAX_UPLOAD_BYTES} bytes"
        )


def compute_sha256_and_size(file_obj):
    """Stream a file object once to compute SHA-256 and size."""
    sha256 = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: file_obj.read(65536), b""):
        sha256.update(chunk)
        size += len(chunk)
    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass
    return sha256.hexdigest(), size



def upload_file(user, path: str, file_obj) -> dict:
    """Upload a file: validate, replicate to k nodes, record metadata atomically.

    Returns a dict with path, version, size, sha256, replicas.
    """
    # Validate path (�10)
    normalized_path, department = validate_path(path)

    # Check write permission (�9)
    check_write_permission(user, department)

    # Compute SHA-256 and size by streaming once (�8.1 step 3)
    file_obj.seek(0)
    sha256_hex, size = compute_sha256_and_size(file_obj)

    # Check size limit
    check_size(size)

    # Choose k alive nodes with enough free space (�8.1 step 4)
    try:
        nodes = choose_nodes(min_free_bytes=size)
    except NotEnoughNodesError as exc:
        raise NotEnoughNodesUploadError(str(exc))

    # Replicate to k nodes (�8.1 step 5)
    successful_nodes = []
    blob_id = uuid.uuid4()
    file_obj.seek(0)
    file_data = file_obj.read()

    for node in nodes:
        try:
            written_size, written_sha256 = put_blob(node, blob_id, file_data)
            successful_nodes.append(node)
            logger.info(
                "Replicated to %s: size=%s sha256=%s",
                node.name, written_size, written_sha256,
            )
        except NodeUnavailableError:
            logger.warning("Replication to %s failed, trying next node", node.name)

    if len(successful_nodes) < settings.REPLICATION_FACTOR:
        # Not enough replicas � delete partial blobs (�8.1 step 5)
        for node in successful_nodes:
            try:
                delete_blob(node, blob_id)
            except NodeUnavailableError:
                pass
        raise NotEnoughNodesUploadError(
            f"Only {len(successful_nodes)}/{settings.REPLICATION_FACTOR} replicas succeeded"
        )

    # Atomic DB write (�12: transaction.atomic + select_for_update on FileEntry)
    with transaction.atomic():
        entry = FileEntry.objects.select_for_update().filter(path=normalized_path).first()
        if entry is None:
            entry = FileEntry.objects.create(
                path=normalized_path,
                owner=user,
                department=department,
            )

        # Version number = max + 1
        latest = entry.versions.order_by("-number").first()
        version_number = (latest.number + 1) if latest else 1

        version = FileVersion.objects.create(
            id=blob_id,
            entry=entry,
            number=version_number,
            size=size,
            sha256=sha256_hex,
            replication_factor=len(successful_nodes),
        )

        # Create Replica rows
        for node in successful_nodes:
            Replica.objects.create(version=version, node=node)

    logger.info(
        "Upload complete: path=%s version=%d size=%d sha256=%s replicas=%s",
        normalized_path, version_number, size, sha256_hex,
        [n.name for n in successful_nodes],
    )

    return {
        "path": normalized_path,
        "version": version_number,
        "size": size,
        "sha256": sha256_hex,
        "replicas": [n.name for n in successful_nodes],
    }

class DownloadError(Exception):
    """Base exception for download failures."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FileNotFoundError(DownloadError):
    def __init__(self, detail: str):
        super().__init__("not_found", detail)


class AllReplicasUnavailableError(DownloadError):
    def __init__(self, detail: str):
        super().__init__("all_replicas_unavailable", detail)


class IntegrityFailedError(DownloadError):
    def __init__(self, detail: str):
        super().__init__("integrity_failed", detail)


def check_read_permission(user, department) -> None:
    """Check that user can read from the given department."""
    if user.is_superuser:
        return
    if not user.groups.filter(pk=department.pk).exists():
        raise PermissionDeniedError(
            f"user '{user.username}' is not in department '{department.name}'"
        )


def download_file(user, path: str, version_number: int | None = None):
    """Download a file: find version, try replicas in order, verify SHA-256, failover.

    Returns (file_version, data_bytes, node_name) or raises DownloadError.
    """
    # Validate path (�10)
    normalized_path, department = validate_path(path)

    # Check read permission (�9)
    check_read_permission(user, department)

    # Find the FileEntry
    try:
        entry = FileEntry.objects.get(path=normalized_path)
    except FileEntry.DoesNotExist:
        raise FileNotFoundError(f"path '{normalized_path}' not found")

    # Find the version
    if version_number is not None:
        try:
            version = entry.versions.get(number=version_number)
        except FileVersion.DoesNotExist:
            raise FileNotFoundError(f"version {version_number} not found for '{normalized_path}'")
    else:
        version = entry.latest_version()
        if version is None:
            raise FileNotFoundError(f"no versions for '{normalized_path}'")

    # Get alive replicas for this version, ordered by verified_at desc then id
    alive_replicas = (
        Replica.objects.filter(version=version, node__is_alive=True)
        .select_related("node")
        .order_by("-verified_at", "id")
    )

    if not alive_replicas.exists():
        raise AllReplicasUnavailableError(
            f"no alive replicas for '{normalized_path}' version {version.number}"
        )

    last_error = None
    for replica in alive_replicas:
        node = replica.node
        try:
            data = get_blob(node, version.id)
        except NodeUnavailableError as exc:
            last_error = exc
            logger.warning("Replica %s unavailable for download: %s", node.name, exc)
            continue

        if data is None:
            # Blob missing on node � try next replica
            logger.warning("Blob missing on node %s for version %s", node.name, version.id)
            continue

        # Verify SHA-256 (�8.2: integrity check on download)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != version.sha256:
            logger.warning(
                "Checksum mismatch on node %s for version %s: expected %s, got %s",
                node.name, version.id, version.sha256, actual_sha256,
            )
            last_error = IntegrityFailedError(
                f"checksum mismatch on replica {node.name}"
            )
            continue

        # Success � update verified_at
        from django.utils import timezone
        replica.verified_at = timezone.now()
        replica.save(update_fields=["verified_at"])

        return version, data, node.name

    # All replicas failed (node down, blob missing, or checksum mismatch)
    if last_error:
        logger.warning(
            "All replicas failed for %s version %s: %s",
            normalized_path, version.number, last_error,
        )
    raise AllReplicasUnavailableError(
        f"all {alive_replicas.count()} replicas unavailable for '{normalized_path}'"
    )

def _repair_version(version: FileVersion) -> int:
    """Restore missing replicas for one version and return the number added."""
    with transaction.atomic():
        locked_version = FileVersion.objects.select_for_update().get(pk=version.pk)
        alive_replicas = list(
            locked_version.replicas.filter(node__is_alive=True).select_related("node")
        )
        needed = locked_version.replication_factor - len(alive_replicas)
        if needed <= 0:
            return 0

        source_data = None
        source_node = None
        for replica in alive_replicas:
            try:
                candidate = get_blob(replica.node, locked_version.id)
            except NodeUnavailableError:
                continue
            if candidate is not None and hashlib.sha256(candidate).hexdigest() == locked_version.sha256:
                source_data = candidate
                source_node = replica.node
                break

        if source_data is None or source_node is None:
            logger.warning("No verified source for version %s", locked_version.id)
            return 0

        existing_node_ids = {replica.node_id for replica in locked_version.replicas.all()}
        candidates = [
            node
            for node in choose_nodes(k=StorageNode.objects.filter(is_alive=True).count(), min_free_bytes=locked_version.size)
            if node.id not in existing_node_ids
        ]

        repaired = 0
        for target in candidates:
            if repaired >= needed:
                break
            try:
                written_size, written_sha256 = put_blob(target, locked_version.id, source_data)
                if written_size != locked_version.size or written_sha256 != locked_version.sha256:
                    logger.warning("Node %s returned invalid data for version %s", target.name, locked_version.id)
                    continue
                Replica.objects.get_or_create(
                    version=locked_version,
                    node=target,
                    defaults={"verified_at": timezone.now()},
                )
                repaired += 1
                logger.info("Repaired version %s -> node %s", locked_version.id, target.name)
            except (NodeUnavailableError, ValueError, KeyError):
                logger.exception("Self-heal failed to %s for version %s", target.name, locked_version.id)

        return repaired


def trigger_self_healing() -> dict:
    """Repair every version below its configured replication factor."""
    from django.db.models import Count, Q

    versions = (
        FileVersion.objects.annotate(
            alive_count=Count("replicas", filter=Q(replicas__node__is_alive=True))
        )
        .filter(alive_count__lt=models.F("replication_factor"))
    )
    summary = {"healed": 0, "tried": versions.count(), "skipped": 0}
    for version in versions:
        try:
            repaired = _repair_version(version)
        except Exception:
            logger.exception("Self-heal error for version %s", version.id)
            repaired = 0
        summary["healed"] += repaired
        if repaired == 0:
            summary["skipped"] += 1
    return summary
