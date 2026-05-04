"""WSGI config for fk_cesis_mms."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")

application = get_wsgi_application()
