"""Master-to-node RPC client."""

import logging
import uuid

import requests
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)
NODE_REQUEST_TIMEOUT = (5, 30)


class NodeClientError(Exception):
    """Base exception for node client errors."""


class NodeUnavailableError(NodeClientError):
    """Raised when a node is unreachable or returns an error."""


def _master_token() -> str:
    """Create a signed master token for node requests."""
    return signing.dumps(
        {"role": "master", "name": "master"},
        key=settings.CLUSTER_SECRET,
    )


def put_blob(node, blob_id: uuid.UUID, data: bytes) -> tuple[int, str]:
    """PUT a blob to a storage node."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = requests.put(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            timeout=NODE_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("PUT to node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if response.status_code not in (200, 201):
        logger.warning("PUT to node %s returned %s", node.name, response.status_code)
        raise NodeUnavailableError(f"Node {node.name} returned {response.status_code}")

    try:
        body = response.json()
        return int(body["size"]), str(body["sha256"])
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("PUT to node %s returned invalid JSON", node.name)
        raise NodeUnavailableError(
            f"Node {node.name} returned an invalid response"
        ) from exc


def get_blob(node, blob_id: uuid.UUID) -> bytes | None:
    """GET a blob from a storage node, returning None when it is missing."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=NODE_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("GET from node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning("GET from node %s returned %s", node.name, response.status_code)
        raise NodeUnavailableError(f"Node {node.name} returned {response.status_code}")
    return response.content


def delete_blob(node, blob_id: uuid.UUID) -> None:
    """DELETE a blob from a storage node. The operation is idempotent."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = requests.delete(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=NODE_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("DELETE from node %s failed (ignored): %s", node.name, exc)
        return

    if response.status_code not in (200, 204):
        logger.warning("DELETE from node %s returned %s", node.name, response.status_code)
