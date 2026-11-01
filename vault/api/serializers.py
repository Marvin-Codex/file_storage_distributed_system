"""API serializers for the master."""

from rest_framework import serializers


class FileUploadSerializer(serializers.Serializer):
    """Serializer for POST /api/files/upload/ multipart requests."""

    path = serializers.CharField(max_length=512)
    file = serializers.FileField()


class FileUploadResponseSerializer(serializers.Serializer):
    """Serializer for the 201 upload response."""

    path = serializers.CharField()
    version = serializers.IntegerField()
    size = serializers.IntegerField()
    sha256 = serializers.CharField()
    replicas = serializers.ListField(child=serializers.CharField())


class ErrorResponseSerializer(serializers.Serializer):
    """Standard error response shape (§7.1)."""

    error = serializers.CharField()
    detail = serializers.CharField()