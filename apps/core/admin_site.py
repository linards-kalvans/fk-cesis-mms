"""Custom admin site — reorders the app list so the most-used app is first."""

from django.contrib import admin


class FkAdminSite(admin.AdminSite):
    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Stable sort: registrations first, every other app keeps Django's
        # default (alphabetical) order.
        app_list.sort(key=lambda app: app["app_label"] != "registrations")
        return app_list
