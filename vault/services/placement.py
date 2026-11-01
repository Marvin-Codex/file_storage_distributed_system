"""Node placement — choose k alive nodes with the most free space."""

from django.conf import settings
from ..models import StorageNode


class NotEnoughNodesError(Exception):
    """Raised when fewer than REPLICATION_FACTOR alive nodes are available."""
    pass


def choose_nodes(k: int | None = None, min_free_bytes: int = 0) -> list[StorageNode]:
    """Select k alive nodes with enough free space, most free space first.

    Args:
        k: Number of replicas needed. Defaults to REPLICATION_FACTOR.
        min_free_bytes: Minimum free bytes required on each node.

    Returns:
        List of StorageNode instances, ordered by free_bytes descending.

    Raises:
        NotEnoughNodesError: If fewer than k qualifying nodes exist.
    """
    if k is None:
        k = settings.REPLICATION_FACTOR

    nodes = list(
        StorageNode.objects.filter(is_alive=True)
        .exclude(capacity_bytes__lt=min_free_bytes)
        .order_by("-capacity_bytes", "name")
    )

    # Filter by actual free bytes (capacity - used)
    qualifying = [n for n in nodes if n.free_bytes >= min_free_bytes]

    if len(qualifying) < k:
        raise NotEnoughNodesError(
            f"Need {k} alive nodes with {min_free_bytes} free bytes, found {len(qualifying)}"
        )

    return qualifying[:k]