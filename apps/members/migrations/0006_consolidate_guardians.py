from django.db import migrations


def forwards(apps, schema_editor):
    from apps.members.services import consolidate_guardians

    consolidate_guardians(
        guardian_model=apps.get_model("members", "Guardian"),
        account_model=apps.get_model("accounts", "ParentAccount"),
        member_model=apps.get_model("members", "Member"),
        application_model=apps.get_model("registrations", "RegistrationApplication"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0005_traininggroup_uniq_training_group_name_ci"),
        ("accounts", "0005_emailverificationcode_code_hash"),
        ("registrations", "0010_remove_registrationapplication_guardian_declared_address_and_more"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
