# Generated migration for parent identity gate.

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("registrations", "0001_initial"),
    ]

    operations = [
        # Make parent_account nullable for claimed-email drafts
        migrations.AlterField(
            model_name="registrationapplication",
            name="parent_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="applications",
                to="accounts.parentaccount",
            ),
        ),
        # Add claimed_email field
        migrations.AddField(
            model_name="registrationapplication",
            name="claimed_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        # Add draft_session_key field
        migrations.AddField(
            model_name="registrationapplication",
            name="draft_session_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
