"""Upload orchestration — replicate a file to k nodes and record metadata."""

import hashlib
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import models, transaction
from django.utils import timezone

from ..models import FileEntry, FileVersion, Replica
from .node_client import NodeUnavailableError, delete_blob, get_blob, put_blob
from .placement import NotEnoughNodesError, eligible_nodes

logger = logging.getLogger(__name__)
User = get_user_model()


def _iter_chunks(file_obj):
    while True:
        chunk = file_obj.read(65536)
        if not chunk:
            return
        yield chunk


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


def _validate_virtual_path(path: str, *, allow_trailing_slash: bool):
    """Validate and normalize a virtual path, returning its department."""
    if not isinstance(path, str) or not path:
        raise InvalidPathError("path is required")
    if not path.startswith("/"):
        raise InvalidPathError("path must start with '/'")
    if len(path) > 512:
        raise InvalidPathError("path exceeds 512 characters")
    if "\\" in path:
        raise InvalidPathError("path must not contain backslashes")
    if "\x00" in path:
        raise InvalidPathError("path must not contain null bytes")
    for ch in path:
        if ord(ch) < 32 or ord(ch) == 127:
            raise InvalidPathError("path contains control characters")
    while "//" in path:
        path = path.replace("//", "/")
    segments = [s for s in path.split("/") if s]
    if not allow_trailing_slash and path.endswith("/"):
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
    normalized = "/" + "/".join(segments) + ("/" if allow_trailing_slash else "")
    if len(normalized) > 512:
        raise InvalidPathError("path exceeds 512 characters")
    return normalized, department


def validate_path(path: str):
    """Validate and normalize a virtual file path."""
    return _validate_virtual_path(path, allow_trailing_slash=False)


def validate_prefix(prefix: str):
    """Validate and normalize a virtual directory prefix."""
    if not prefix:
        raise InvalidPathError("prefix is required")
    return _validate_virtual_path(prefix, allow_trailing_slash=True)


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

    # Choose all eligible nodes so failed placements can use fallbacks.
    try:
        nodes = eligible_nodes(min_free_bytes=size)
        if len(nodes) < settings.REPLICATION_FACTOR:
            raise NotEnoughNodesError(
                f"Need {settings.REPLICATION_FACTOR} alive nodes with {size} free bytes, "
                f"found {len(nodes)}"
            )
    except NotEnoughNodesError as exc:
        raise NotEnoughNodesUploadError(str(exc))

    # Replicate to k nodes (�8.1 step 5)
    successful_nodes = []
    blob_id = uuid.uuid4()

    for node in nodes:
        try:
            file_obj.seek(0)
            written_size, written_sha256 = put_blob(node, blob_id, file_obj)
            if written_size != size or written_sha256 != sha256_hex:
                logger.warning(
                    "Node %s failed integrity validation for upload %s",
                    node.name,
                    blob_id,
                )
                delete_blob(node, blob_id)
                continue
            successful_nodes.append(node)
            logger.info(
                "Replicated to %s: size=%s sha256=%s",
                node.name, written_size, written_sha256,
            )
        except NodeUnavailableError as exc:
            logger.warning(
                "Replication to %s failed, trying next node: %s",
                node.name,
                exc,
            )

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
        entry, _ = FileEntry.objects.get_or_create(
            path=normalized_path,
            defaults={"owner": user, "department": department},
        )
        entry = FileEntry.objects.select_for_update().get(pk=entry.pk)

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
            Replica.objects.create(
                version=version,
                node=node,
                verified_at=timezone.now(),
            )

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
            replica.verified_at = None
            replica.save(update_fields=["verified_at"])
            continue

        # Verify SHA-256 (�8.2: integrity check on download)
        actual_sha256 = hashlib.sha256()
        for chunk in _iter_chunks(data):
            actual_sha256.update(chunk)
        actual_sha256 = actual_sha256.hexdigest()
        if actual_sha256 != version.sha256:
            data.close()
            replica.verified_at = None
            replica.save(update_fields=["verified_at"])
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

        data.seek(0)
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
        source_data = None
        healthy_node_ids = set()
        for replica in alive_replicas:
            try:
                candidate = get_blob(replica.node, locked_version.id)
            except NodeUnavailableError:
                continue
            if candidate is None:
                if replica.verified_at is not None:
                    replica.verified_at = None
                    replica.save(update_fields=["verified_at"])
                continue
            checksum = hashlib.sha256()
            for chunk in _iter_chunks(candidate):
                checksum.update(chunk)
            if checksum.hexdigest() == locked_version.sha256:
                healthy_node_ids.add(replica.node_id)
                replica.verified_at = timezone.now()
                replica.save(update_fields=["verified_at"])
                if source_data is not None:
                    candidate.close()
                    continue
                candidate.seek(0)
                source_data = candidate
                continue
            candidate.close()
            if replica.verified_at is not None:
                replica.verified_at = None
                replica.save(update_fields=["verified_at"])

        needed = locked_version.replication_factor - len(healthy_node_ids)
        if needed <= 0:
            if source_data is not None:
                source_data.close()
            return 0

        if source_data is None:
            logger.warning("No verified source for version %s", locked_version.id)
            return 0

        candidates = [
            node
            for node in eligible_nodes(min_free_bytes=locked_version.size)
            if node.id not in healthy_node_ids
        ]

        repaired = 0
        for target in candidates:
            if repaired >= needed:
                break
            try:
                source_data.seek(0)
                written_size, written_sha256 = put_blob(target, locked_version.id, source_data)
                if written_size != locked_version.size or written_sha256 != locked_version.sha256:
                    logger.warning("Node %s returned invalid data for version %s", target.name, locked_version.id)
                    continue
                Replica.objects.update_or_create(
                    version=locked_version,
                    node=target,
                    defaults={"verified_at": timezone.now()},
                )
                repaired += 1
                logger.info("Repaired version %s -> node %s", locked_version.id, target.name)
            except (NodeUnavailableError, ValueError, KeyError):
                logger.exception("Self-heal failed to %s for version %s", target.name, locked_version.id)

        source_data.close()
        return repaired


class DeleteError(UploadError):
    def __init__(self, detail: str):
        super().__init__("delete_incomplete", detail)


def delete_file(user, path: str) -> dict:
    """Delete all versions and replicas after every known node confirms deletion."""
    normalized_path, department = validate_path(path)
    check_write_permission(user, department)

    try:
        entry = FileEntry.objects.get(path=normalized_path)
    except FileEntry.DoesNotExist:
        raise FileNotFoundError(f"path '{normalized_path}' not found")

    failed_nodes = set()
    for replica in Replica.objects.filter(version__entry=entry).select_related("node", "version"):
        try:
            delete_blob(replica.node, replica.version.id)
        except NodeUnavailableError:
            failed_nodes.add(replica.node.name)

    if failed_nodes:
        raise DeleteError(
            f"could not confirm deletion on nodes: {', '.join(sorted(failed_nodes))}"
        )

    entry.delete()
    logger.info("Deleted file path=%s", normalized_path)
    return {"path": normalized_path, "deleted": True}


def trigger_self_healing() -> dict:
    """Repair every version below its configured replication factor."""
    from django.db.models import Count, Q

    cutoff = timezone.now() - timedelta(
        seconds=settings.REPLICA_VERIFY_INTERVAL_SECONDS
    )
    versions = (
        FileVersion.objects.annotate(
            healthy_count=Count(
                "replicas",
                filter=Q(
                    replicas__node__is_alive=True,
                    replicas__verified_at__isnull=False,
                ),
            ),
            stale_count=Count(
                "replicas",
                filter=Q(
                    replicas__node__is_alive=True,
                    replicas__verified_at__lt=cutoff,
                )
                | Q(
                    replicas__node__is_alive=True,
                    replicas__verified_at__isnull=True,
                ),
            ),
        )
        .filter(
            Q(healthy_count__lt=models.F("replication_factor"))
            | Q(stale_count__gt=0)
        )
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
