import logging

from django.db import transaction
from django.utils import timezone

from ..models import Replica, StorageNode
from .node_client import NodeUnavailableError, list_blob_ids

logger = logging.getLogger(__name__)


def reconcile_node(node: StorageNode) -> dict:
    """Compare a node inventory with metadata without deleting untracked blobs."""
    inventory = list_blob_ids(node)
    replicas = list(
        Replica.objects.filter(node=node).select_related("version")
    )
    expected = {replica.version_id for replica in replicas}
    missing = expected - inventory
    untracked = inventory - expected

    with transaction.atomic():
        if missing:
            Replica.objects.filter(
                node=node,
                version_id__in=missing,
            ).update(verified_at=None)
        node.reconciliation_required = False
        node.last_reconciled_at = timezone.now()
        node.save(
            update_fields=["reconciliation_required", "last_reconciled_at"]
        )

    if untracked:
        logger.warning(
            "Node %s has %d untracked blobs; preserving them for inspection",
            node.name,
            len(untracked),
        )
    if missing:
        logger.warning(
            "Node %s is missing %d metadata replicas",
            node.name,
            len(missing),
        )
    return {
        "node": node.name,
        "missing": len(missing),
        "untracked": len(untracked),
    }


def reconcile_required_nodes() -> dict:
    """Reconcile nodes marked after registration or reconnect."""
    summary = {"reconciled": 0, "failed": 0, "missing": 0, "untracked": 0}
    for node in StorageNode.objects.filter(
        is_alive=True,
        reconciliation_required=True,
    ):
        try:
            result = reconcile_node(node)
        except NodeUnavailableError:
            summary["failed"] += 1
            logger.warning("Could not reconcile node %s", node.name)
            continue
        summary["reconciled"] += 1
        summary["missing"] += result["missing"]
        summary["untracked"] += result["untracked"]
    return summary
