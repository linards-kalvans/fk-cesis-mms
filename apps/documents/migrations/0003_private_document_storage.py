"""Migration — switch Document.file to private storage and copy existing files."""

from pathlib import Path
import shutil

from django.conf import settings
from django.db import migrations, models

from apps.documents.storage import PrivateDocumentStorage


def copy_existing_document_files(apps, schema_editor):
    """Copy existing document bytes from MEDIA_ROOT to PRIVATE_DOCUMENTS_ROOT."""
    Document = apps.get_model("documents", "Document")
    old_root = Path(settings.MEDIA_ROOT)
    new_root = Path(settings.PRIVATE_DOCUMENTS_ROOT)
    new_root.mkdir(parents=True, exist_ok=True)

    for document in Document.objects.exclude(file=""):
        relative_name = document.file.name
        source = old_root / relative_name
        destination = new_root / relative_name
        if destination.exists() or not source.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(
                upload_to="private/child-identity/",
                storage=PrivateDocumentStorage(),
            ),
        ),
        migrations.RunPython(copy_existing_document_files, migrations.RunPython.noop),
    ]
