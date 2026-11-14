from django.contrib import admin
from .models import StorageNode, FileEntry, FileVersion, Replica

admin.site.register(StorageNode)
admin.site.register(FileEntry)
admin.site.register(FileVersion)
admin.site.register(Replica)
