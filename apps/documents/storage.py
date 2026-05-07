"""Private document storage — registration identity documents only."""

from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateDocumentStorage(FileSystemStorage):
    """File storage rooted under PRIVATE_DOCUMENTS_ROOT."""

    @property
    def base_location(self) -> str:
        return str(Path(settings.PRIVATE_DOCUMENTS_ROOT))

    @property
    def location(self) -> str:
        return self.base_location


def private_document_old_root() -> Path:
    """Return the old (public) storage root for migration copies."""
    return Path(settings.MEDIA_ROOT)


def private_document_new_root() -> Path:
    """Return the new private storage root."""
    return Path(settings.PRIVATE_DOCUMENTS_ROOT)
