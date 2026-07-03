"""URL configuration for fk_cesis_mms."""

from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as accounts_views
from apps.core.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("admin/documents/", include("apps.documents.urls")),
    path("", include("apps.agreements.urls")),
    path("addresses/", include("apps.addresses.urls")),
    path("", include("apps.registrations.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("register/verify/", accounts_views.verify_one_time_code_view, name="register-verify"),
]
