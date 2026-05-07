"""URL configuration for fk_cesis_mms."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/documents/", include("apps.documents.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.registrations.urls")),
]
