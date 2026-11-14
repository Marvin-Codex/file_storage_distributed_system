from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vault", "0003_storagenode_last_reconciled_at_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="storagenode",
            name="credential_hash",
        ),
        migrations.RemoveField(
            model_name="storagenode",
            name="credential_issued_at",
        ),
        migrations.RemoveField(
            model_name="storagenode",
            name="credential_revoked_at",
        ),
        migrations.DeleteModel(
            name="EnrollmentToken",
        ),
    ]
