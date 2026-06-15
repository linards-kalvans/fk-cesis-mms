"""Custom admin site — fixed left-menu ordering for the staff workflow."""

from django.contrib import admin

# Explicit left-menu order; apps not listed sort last in Django's default order.
_APP_ORDER = (
    "registrations",
    "agreements",
    "billing",
    "members",
    "auth",  # Authentication and Authorization
    "documents",
    "core",
    "django_q",
)


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
        index = {label: i for i, label in enumerate(_APP_ORDER)}
        # Stable sort: listed apps in the fixed order, the rest keep their order.
        app_list.sort(key=lambda app: index.get(app["app_label"], len(_APP_ORDER)))
        return app_list
