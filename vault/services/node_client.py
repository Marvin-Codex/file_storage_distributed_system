"""Master -> node RPC client."""

import uuid
import logging
import requests
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)


class NodeClientError(Exception):
    """Base exception for node client errors."""
    pass


class NodeUnavailableError(NodeClientError):
    """Raised when a node is unreachable or returns an error."""
    pass


def _master_token() -> str:
    """Create a signed master token for node requests."""
    return signing.dumps(
        {"role": "master", "name": "master"},
        key=settings.CLUSTER_SECRET,
    )


def put_blob(node, blob_id: uuid.UUID, data: bytes) -> tuple[int, str]:
    """PUT blob to a storage node.

    Args:
        node: StorageNode instance.
        blob_id: UUID (also the FileVersion.id / blob ID).
        data: File bytes to upload.

    Returns:
        (size, sha256_hex) as reported by the node.

    Raises:
        NodeUnavailableError: If the node rejects the upload.
    """
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        resp = requests.put(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.exception("PUT to node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if resp.status_code not in (200, 201):
        logger.warning("PUT to node %s returned %s", node.name, resp.status_code)
        raise NodeUnavailableError(
            f"Node {node.name} returned {resp.status_code}"
        )

    body = resp.json()
    return int(body["size"]), body["sha256"]


def get_blob(node, blob_id: uuid.UUID) -> bytes | None:
    """GET blob from a storage node.

    Returns None if the blob does not exist (404).
    """
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.exception("GET from node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.warning("GET from node %s returned %s", node.name, resp.status_code)
        raise NodeUnavailableError(
            f"Node {node.name} returned {resp.status_code}"
        )

    return resp.content


def delete_blob(node, blob_id: uuid.UUID) -> None:
    """DELETE blob from a storage node. Idempotent (204 even if missing)."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        requests.delete(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("DELETE from node %s failed (ignored): %s", node.name, exc)