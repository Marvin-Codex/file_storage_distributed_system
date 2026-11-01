"""Heartbeat sender — periodically reports this node to the master.

Usage (as a node):
    ROLE=node NODE_NAME=node1 NODE_ADDRESS=http://127.0.0.1:9001 \\
        NODE_DATA_DIR=./data/node1 MASTER_URL=http://127.0.0.1:8000 \\
        python manage.py run_heartbeat
"""

import json
import logging
import os
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send heartbeats to the master until interrupted."

    def handle(self, *args, **options):
        node_name = settings.NODE_NAME
        node_address = settings.NODE_ADDRESS
        master_url = settings.MASTER_URL.rstrip("/")
        interval = settings.HEARTBEAT_INTERVAL_SECONDS
        data_dir = settings.NODE_DATA_DIR
        capacity = settings.NODE_CAPACITY_BYTES

        if not node_name:
            self.stderr.write("NODE_NAME is required")
            return
        if not node_address:
            self.stderr.write("NODE_ADDRESS is required")
            return
        if not master_url:
            self.stderr.write("MASTER_URL is required")
            return

        self.stdout.write(
            f"Starting heartbeat sender: {node_name} -> {master_url} "
            f"(every {interval}s)"
        )

        while True:
            try:
                self._send_heartbeat(node_name, node_address, data_dir, capacity, master_url)
            except Exception:  # never let one failed heartbeat crash the loop (§12)
                logger.exception("Heartbeat loop error")
            time.sleep(interval)

    def _send_heartbeat(self, name, address, data_dir, capacity, master_url):
        """Send a single heartbeat to the master."""
        used_bytes = self._used_bytes(data_dir)
        payload = {
            "name": name,
            "address": address,
            "capacity_bytes": capacity,
            "used_bytes": used_bytes,
        }

        # Sign with node token (role="node", max age 60s) (§11)
        from django.core import signing
        token = signing.dumps({"role": "node", "name": name}, key=settings.CLUSTER_SECRET)

        url = f"{master_url}/internal/heartbeat/"
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,  # §12: every network call has a timeout
        )
        resp.raise_for_status()
        logger.debug("Heartbeat acknowledged by master: %s", name)

    @staticmethod
    def _used_bytes(data_dir):
        """Sum sizes of all .blob files in NODE_DATA_DIR."""
        total = 0
        try:
            for entry in os.scandir(data_dir):
                if entry.is_file() and entry.name.endswith(".blob"):
                    total += entry.stat().st_size
        except FileNotFoundError:
            pass
        return total