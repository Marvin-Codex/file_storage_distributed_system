from django.contrib import admin
from .models import EnrollmentToken, StorageNode, FileEntry, FileVersion, Replica

admin.site.register(StorageNode)
admin.site.register(EnrollmentToken)
admin.site.register(FileEntry)
admin.site.register(FileVersion)
admin.site.register(Replica)
