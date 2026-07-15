# P12: parent-safe invoice URL filled by payment sync.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0012_billingrecord_first_billing_month_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="billinginvoice",
            name="external_url",
            field=models.URLField(blank=True, default=""),
        ),
    ]
