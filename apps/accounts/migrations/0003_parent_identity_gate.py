# Generated migration for parent identity gate — accounts app.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_magiclinktoken_sent_at"),
    ]

    operations = [
        # Make MagicLinkToken.account nullable for claimed-email flow
        migrations.AlterField(
            model_name="magiclinktoken",
            name="account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="magic_link_tokens",
                to="accounts.parentaccount",
            ),
        ),
        # Add claimed_email field to MagicLinkToken
        migrations.AddField(
            model_name="magiclinktoken",
            name="claimed_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
