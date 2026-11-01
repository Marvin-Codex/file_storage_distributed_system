"""Safe disk storage for node blobs."""

import hashlib
import os
import uuid
from django.conf import settings


def _blob_path(blob_id: uuid.UUID) -> str:
    """Build safe filesystem path from UUID only, inside NODE_DATA_DIR."""
    return os.path.join(settings.NODE_DATA_DIR, f"{blob_id}.blob")


def _ensure_data_dir() -> None:
    os.makedirs(settings.NODE_DATA_DIR, exist_ok=True)


def write_blob(blob_id: uuid.UUID, data: bytes) -> tuple[int, str]:
    """Write blob atomically: temp file, fsync, os.replace.

    Returns (size, sha256_hexdigest).
    """
    _ensure_data_dir()
    final_path = _blob_path(blob_id)
    tmp_path = final_path + ".tmp"

    sha256 = hashlib.sha256(data)
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, final_path)
    return len(data), sha256.hexdigest()


def read_blob(blob_id: uuid.UUID) -> bytes | None:
    """Read blob content. Returns None if blob does not exist."""
    path = _blob_path(blob_id)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


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