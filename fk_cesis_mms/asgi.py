"""ASGI config for fk_cesis_mms."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")

application = get_asgi_application()
