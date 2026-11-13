"""Master-to-node RPC client."""

import logging
import tempfile
import uuid
from typing import BinaryIO

import requests
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)
NODE_REQUEST_TIMEOUT = (5, 30)

# Allow internal cluster traffic to use configured system/environment proxies.
_session = requests.Session()
_session.trust_env = False


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


def put_blob(node, blob_id: uuid.UUID, data: BinaryIO | bytes) -> tuple[int, str]:
    """PUT a blob to a storage node."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = _session.put(
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


def get_blob(node, blob_id: uuid.UUID) -> BinaryIO | None:
    """GET a blob into a temporary stream, returning None when it is missing."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = _session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=NODE_REQUEST_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as exc:
        logger.exception("GET from node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning("GET from node %s returned %s", node.name, response.status_code)
        raise NodeUnavailableError(f"Node {node.name} returned {response.status_code}")
    temporary_file = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
    try:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                temporary_file.write(chunk)
        temporary_file.seek(0)
        return temporary_file
    except requests.RequestException as exc:
        temporary_file.close()
        logger.exception("GET body from node %s failed", node.name)
        raise NodeUnavailableError(f"Node {node.name} transfer failed: {exc}") from exc


def delete_blob(node, blob_id: uuid.UUID) -> None:
    """DELETE a blob from a storage node. The operation is idempotent."""
    url = f"{node.address.rstrip('/')}/store/{blob_id}/"
    token = _master_token()
    try:
        response = _session.delete(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=NODE_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("DELETE from node %s failed: %s", node.name, exc)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if response.status_code not in (200, 204):
        logger.warning("DELETE from node %s returned %s", node.name, response.status_code)
        raise NodeUnavailableError(f"Node {node.name} returned {response.status_code}")


def list_blob_ids(node) -> set[uuid.UUID]:
    """Return opaque blob IDs currently present on a node."""
    url = f"{node.address.rstrip('/')}/inventory/"
    token = _master_token()
    try:
        response = _session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=NODE_REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("INVENTORY from node %s failed: %s", node.name, exc)
        raise NodeUnavailableError(f"Node {node.name} unreachable: {exc}") from exc

    if response.status_code != 200:
        logger.warning(
            "INVENTORY from node %s returned %s",
            node.name,
            response.status_code,
        )
        raise NodeUnavailableError(f"Node {node.name} returned {response.status_code}")
    try:
        blob_ids = response.json()["blobs"]
        return {uuid.UUID(blob_id) for blob_id in blob_ids}
    except (ValueError, KeyError, TypeError) as exc:
        raise NodeUnavailableError(
            f"Node {node.name} returned an invalid inventory"
        ) from exc
