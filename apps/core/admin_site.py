"""Custom admin site — reorders the app list so the most-used app is first."""

from django.contrib import admin


class FkAdminSite(admin.AdminSite):
    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Hide ParentAccount from the menu/index — it's managed via the Guardian
        # ("Vecāki") page. It stays registered, so its change URL still resolves.
        for app in app_list:
            if app["app_label"] == "accounts":
                app["models"] = [
                    m for m in app["models"] if m["object_name"] != "ParentAccount"
                ]
        app_list = [app for app in app_list if app["models"]]
        # registrations first; the rest keep Django's default order.
        app_list.sort(key=lambda app: app["app_label"] != "registrations")
        return app_list
