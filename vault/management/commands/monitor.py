import logging
import time
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from vault.models import StorageNode
from vault.services.reconciliation import reconcile_required_nodes
from vault.services.replication import trigger_self_healing

logger = logging.getLogger(__name__)
MONITOR_LOCK_ID = 875321


@contextmanager
def monitor_lock():
    """Run one monitor instance at a time on PostgreSQL."""
    if connection.vendor != "postgresql":
        yield True
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [MONITOR_LOCK_ID])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [MONITOR_LOCK_ID])


def detect_failures(now=None) -> list[str]:
    """Mark silent nodes dead and return the nodes whose state changed."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.NODE_DEAD_AFTER_SECONDS)
    changed = []
    for node in StorageNode.objects.all():
        should_be_alive = node.last_heartbeat is not None and node.last_heartbeat >= cutoff
        if node.is_alive != should_be_alive:
            node.is_alive = should_be_alive
            node.save(update_fields=["is_alive"])
            changed.append(node.name)
            logger.info("Node %s marked %s", node.name, "alive" if should_be_alive else "dead")
    return changed


def run_cycle() -> dict:
    """Run failure detection, reconciliation, and one idempotent repair pass."""
    changed = detect_failures()
    reconciliation = reconcile_required_nodes()
    repair_summary = trigger_self_healing()
    return {"changed_nodes": changed, **reconciliation, **repair_summary}


class Command(BaseCommand):
    help = "Periodic monitor: failure detection and self-healing re-replication."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one detection and repair cycle, then exit.",
        )

    def handle(self, *args, **options):
        dead_after = settings.NODE_DEAD_AFTER_SECONDS
        interval = settings.MONITOR_INTERVAL_SECONDS
        self.stdout.write(
            f"Starting LANVault monitor (dead after {dead_after}s, check every {interval}s)"
        )

        with monitor_lock() as acquired:
            if not acquired:
                self.stderr.write("Another monitor instance is already running")
                return

            while True:
                summary = run_cycle()
                self.stdout.write(
                    f"Monitor cycle: changed={len(summary['changed_nodes'])}, "
                    f"reconciled={summary['reconciled']}, "
                    f"reconcile_failed={summary['failed']}, "
                    f"tried={summary['tried']}, healed={summary['healed']}, "
                    f"skipped={summary['skipped']}"
                )
                if options["once"]:
                    return
                time.sleep(interval)
