import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

_session = requests.Session()
_session.trust_env = False


class Command(BaseCommand):
    help = "Enroll this storage node with a LANVault master."

    def add_arguments(self, parser):
        parser.add_argument("--master", required=True)
        parser.add_argument("--token", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--address", default="")
        parser.add_argument("--capacity-bytes", type=int, default=None)

    def handle(self, *args, **options):
        master_url = options["master"].rstrip("/")
        address = options["address"] or settings.NODE_ADDRESS
        capacity = options["capacity_bytes"]
        if not address:
            raise CommandError("--address or NODE_ADDRESS is required")
        if capacity is None:
            capacity = settings.NODE_CAPACITY_BYTES
        if capacity <= 0:
            raise CommandError("--capacity-bytes or NODE_CAPACITY_BYTES must be positive")

        try:
            response = _session.post(
                f"{master_url}/internal/enroll/",
                json={
                    "token": options["token"],
                    "name": options["name"],
                    "address": address,
                    "capacity_bytes": capacity,
                },
                timeout=(5, 30),
            )
        except requests.RequestException as exc:
            raise CommandError(f"enrollment request failed: {exc}") from exc

        if response.status_code != 201:
            raise CommandError(
                f"enrollment rejected by master (status {response.status_code})"
            )
        try:
            payload = response.json()
            credential = payload["credential"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError("master returned an invalid enrollment response") from exc

        self.stdout.write(f"NODE_CREDENTIAL={credential}")
        self.stdout.write(
            "Set NODE_CREDENTIAL to this value before starting run_heartbeat."
        )
