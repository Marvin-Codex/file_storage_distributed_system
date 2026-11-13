"""Safe disk storage for node blobs."""

import hashlib
import io
import os
import uuid
from typing import BinaryIO

from django.conf import settings


def _blob_path(blob_id: uuid.UUID) -> str:
    """Build safe filesystem path from UUID only, inside NODE_DATA_DIR."""
    return os.path.join(settings.NODE_DATA_DIR, f"{blob_id}.blob")


def _ensure_data_dir() -> None:
    os.makedirs(settings.NODE_DATA_DIR, exist_ok=True)


def write_blob(blob_id: uuid.UUID, data: BinaryIO | bytes) -> tuple[int, str]:
    """Write blob atomically: temp file, fsync, os.replace.

    Returns (size, sha256_hexdigest).
    """
    _ensure_data_dir()
    final_path = _blob_path(blob_id)
    tmp_path = os.path.join(
        settings.NODE_DATA_DIR,
        f".{blob_id}.{uuid.uuid4()}.tmp",
    )

    source = io.BytesIO(data) if isinstance(data, bytes) else data
    sha256 = hashlib.sha256()
    size = 0
    try:
        with open(tmp_path, "wb") as destination:
            for chunk in iter(lambda: source.read(65536), b""):
                destination.write(chunk)
                sha256.update(chunk)
                size += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())

        os.replace(tmp_path, final_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return size, sha256.hexdigest()


def open_blob(blob_id: uuid.UUID) -> BinaryIO | None:
    """Open a blob for streaming, or return None if it does not exist."""
    path = _blob_path(blob_id)
    if not os.path.exists(path):
        return None
    return open(path, "rb")


def list_blob_ids() -> set[uuid.UUID]:
    """Return UUIDs for complete blob files in the node data directory."""
    _ensure_data_dir()
    blob_ids = set()
    for entry in os.scandir(settings.NODE_DATA_DIR):
        if not entry.is_file() or not entry.name.endswith(".blob"):
            continue
        try:
            blob_ids.add(uuid.UUID(entry.name[:-5]))
        except ValueError:
            continue
    return blob_ids


def delete_blob(blob_id: uuid.UUID) -> bool:
    """Delete blob. Returns True if existed, False if already gone."""
    path = _blob_path(blob_id)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def free_space() -> int:
    """Return free bytes available on the NODE_DATA_DIR filesystem."""
    _ensure_data_dir()
    if hasattr(os, "statvfs"):
        stat = os.statvfs(settings.NODE_DATA_DIR)
        return stat.f_frsize * stat.f_bavail
    # Windows fallback
    import ctypes
    free = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(settings.NODE_DATA_DIR),
        None,
        None,
        ctypes.byref(free),
    )
    return free.value