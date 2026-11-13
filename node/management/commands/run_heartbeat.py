"""Heartbeat sender for storage nodes."""

import logging
import os
import time

import requests
from django.conf import settings
from django.core import signing
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# Internal cluster traffic must never go through a system/environment proxy.
_session = requests.Session()
_session.trust_env = False


class Command(BaseCommand):
    help = "Send heartbeats to the master until interrupted."

    def handle(self, *args, **options):
        node_name = settings.NODE_NAME
        node_address = settings.NODE_ADDRESS
        master_url = settings.MASTER_URL.rstrip("/")
        interval = settings.HEARTBEAT_INTERVAL_SECONDS
        data_dir = settings.NODE_DATA_DIR
        capacity = settings.NODE_CAPACITY_BYTES
        credential = os.environ.get("NODE_CREDENTIAL", "")

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
                self._send_heartbeat(
                    node_name, node_address, data_dir, capacity, master_url, credential
                )
            except requests.RequestException as exc:
                logger.warning("Heartbeat failed for node %s: %s", node_name, exc)
            except (OSError, ValueError):
                logger.exception("Heartbeat loop error")
            time.sleep(interval)

    def _send_heartbeat(
        self, name, address, data_dir, capacity, master_url, credential=""
    ):
        """Send a single heartbeat to the master."""
        payload = {
            "name": name,
            "address": address,
            "capacity_bytes": capacity,
            "used_bytes": self._used_bytes(data_dir),
        }
        token = credential or signing.dumps(
            {"role": "node", "name": name}, key=settings.CLUSTER_SECRET
        )
        response = _session.post(
            f"{master_url}/internal/heartbeat/",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(5, 30),
        )
        response.raise_for_status()
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