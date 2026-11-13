from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from vault.models import StorageNode


class Command(BaseCommand):
    help = "Revoke a storage node credential."

    def add_arguments(self, parser):
        parser.add_argument("name")

    def handle(self, *args, **options):
        try:
            node = StorageNode.objects.get(name=options["name"])
        except StorageNode.DoesNotExist as exc:
            raise CommandError("unknown storage node") from exc

        node.credential_revoked_at = timezone.now()
        node.save(update_fields=["credential_revoked_at"])
        self.stdout.write(f"Revoked credential for {node.name}")
