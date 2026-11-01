p = r'C:\Users\Marvin\Desktop\Storage Distributed System\vault\services\replication.py'
with open(p) as f:
    content = f.read()

download_func = '''

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
    # Validate path (§10)
    normalized_path, department = validate_path(path)

    # Check read permission (§9)
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
            # Blob missing on node — try next replica
            logger.warning("Blob missing on node %s for version %s", node.name, version.id)
            continue

        # Verify SHA-256 (§8.2: integrity check on download)
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

        # Success — update verified_at
        from django.utils import timezone
        replica.verified_at = timezone.now()
        replica.save(update_fields=["verified_at"])

        return version, data, node.name

    # All replicas failed
    if last_error:
        raise last_error
    raise AllReplicasUnavailableError(
        f"all {alive_replicas.count()} replicas unavailable for '{normalized_path}'"
    )
'''

if 'class DownloadError' not in content:
    content = content.rstrip() + download_func
    with open(p, 'w', newline='\r\n') as f:
        f.write(content)
    print('Added download service functions')
else:
    print('Download functions already exist')