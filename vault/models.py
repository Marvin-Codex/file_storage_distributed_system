import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone


class StorageNode(models.Model):
    name = models.CharField(max_length=64, unique=True)
    address = models.URLField(unique=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    is_alive = models.BooleanField(default=False)
    capacity_bytes = models.BigIntegerField(default=0)
    used_bytes = models.BigIntegerField(default=0)
    reconciliation_required = models.BooleanField(default=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)

    @property
    def free_bytes(self):
        return max(self.capacity_bytes - self.used_bytes, 0)

    def __str__(self):
        return self.name


class FileEntry(models.Model):
    path = models.CharField(max_length=512, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    department = models.ForeignKey(Group, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)

    def latest_version(self):
        return self.versions.order_by("-number").first()


class FileVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(FileEntry, related_name="versions", on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    size = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    replication_factor = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = (("entry", "number"),)


class Replica(models.Model):
    version = models.ForeignKey(FileVersion, related_name="replicas", on_delete=models.CASCADE)
    node = models.ForeignKey(StorageNode, related_name="replicas", on_delete=models.CASCADE)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("version", "node"),)
