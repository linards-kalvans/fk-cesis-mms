from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_emailverificationcode"),
    ]

    operations = [
        migrations.RenameField(
            model_name="emailverificationcode",
            old_name="code",
            new_name="code_hash",
        ),
        migrations.AlterField(
            model_name="emailverificationcode",
            name="code_hash",
            field=models.CharField(max_length=256),
        ),
    ]
