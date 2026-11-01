"""Monitor management command — failure detection + self-healing re-replication.

Usage (as master):
    python manage.py monitor

The monitor:
  1. Runs in a loop at MONITOR_INTERVAL_SECONDS (default 5s).
  2. Marks nodes as dead after NODE_DEAD_AFTER_SECONDS (default 15s) of no heartbeat.
  3. Triggers self-healing re-replication for under-replicated versions.
  4. Is idempotent — safe to run repeatedly.

Per README §14 M6 and §12 (concurrency rules).
"""

import time
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)

from vault.models import StorageNode


class Command(BaseCommand):
    help = "Periodic monitor: failure detection + self-healing re-replication."

    def handle(self, *args, **options):
        dead_after = 15  # NODE_DEAD_AFTER_SECONDS default
        interval = 5     # MONITOR_INTERVAL_SECONDS default

        self.stdout.write(
            f"Starting LANVault monitor (dead after {dead_after}s, check every {interval}s)"
        )

        # Track last heartbeat time per node name
        last_heartbeat = {}

        while True:
            now = timezone.now()

            # 1. Failure detection: check node aliveness
            for node in StorageNode.objects.all():
                age = (now - node.last_heartbeat).total_seconds() if node.last_heartbeat else float("inf")
                was_alive = node.is_alive
                is_now_dead = age > dead_after

                if is_now_dead and was_alive:
                    node.is_alive = False
                    node.save(update_fields=["is_alive", "last_heartbeat"])
                    self.stdout.write(f"Node {node.name} marked dead (silence {age:.0f}s)")
                    # Trigger re-replication when node goes dead
                    from ..services.replication import trigger_self_healing
                    trigger_self_healing()

                elif not is_now_dead and not was_alive:
                    node.is_alive = True
                    node.save(update_fields=["is_alive"])
                    self.stdout.write(f"Node {node.name} recovered")

            # Self-healing re-replication triggered inside node-check loop

            time.sleep(interval)
''')