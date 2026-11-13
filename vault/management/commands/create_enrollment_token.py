from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from vault.models import EnrollmentToken
from vault.services.tokens import hash_enrollment_token, make_enrollment_token


class Command(BaseCommand):
    help = "Create a single-use storage-node enrollment token."

    def add_arguments(self, parser):
        parser.add_argument(
            "--expires-in",
            type=int,
            default=900,
            help="Token lifetime in seconds (default: 900).",
        )

    def handle(self, *args, **options):
        expires_in = options["expires_in"]
        if expires_in <= 0:
            raise CommandError("--expires-in must be greater than zero")

        token = make_enrollment_token()
        EnrollmentToken.objects.create(
            token_hash=hash_enrollment_token(token),
            expires_at=timezone.now() + timedelta(seconds=expires_in),
        )
        self.stdout.write(token)
