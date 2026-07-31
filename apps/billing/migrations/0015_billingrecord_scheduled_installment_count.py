from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0014_remove_membershipplan_sibling_discount_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingrecord",
            name="scheduled_installment_count",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
