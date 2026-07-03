"""Core app config for FK Cēsis MMS."""

from django.apps import AppConfig

# Import the module, not the AdminConfig class itself: Django's AppConfig
# auto-discovery scans this module's class namespace for AppConfig subclasses,
# so a bare `AdminConfig` name here would become a spurious candidate for the
# plain "apps.core" INSTALLED_APPS entry and collide with CoreConfig.
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    name = "apps.core"
    default_auto_field = "django.db.models.BigAutoField"


class FkAdminConfig(admin_apps.AdminConfig):
    # Referenced explicitly by path in INSTALLED_APPS; opt out of being an
    # auto-discovery candidate so it never collides with CoreConfig for the
    # "apps.core" entry.
    default = False
    default_site = "apps.core.admin_site.FkAdminSite"
