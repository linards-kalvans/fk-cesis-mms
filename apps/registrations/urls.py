"""URL routing for registration workflow."""

from django.urls import path

from apps.registrations import views

app_name = "registrations"

urlpatterns = [
    path("applications/new/", views.new_application, name="new-application"),
    path("register/", views.start_registration, name="start-registration"),
    # Canonical application workspace
    path("applications/<int:application_id>/", views.application_workspace, name="application-workspace"),
    # Legacy routes — redirect to canonical workspace
    path("applications/<int:application_id>/edit/", views.redirect_to_workspace, name="edit-registration"),
    path("applications/<int:application_id>/summary/", views.redirect_to_workspace, name="view-registration-summary"),
    path("applications/<int:application_id>/detail/", views.redirect_to_workspace, name="view-registration-detail"),
    path("applications/<int:application_id>/submit/", views.submit_registration, name="submit-registration"),
    # P3.5 async upload endpoint
    path(
        "applications/<int:application_id>/documents/",
        views.async_document_upload,
        name="async-document-upload",
    ),
    path(
        "applications/<int:application_id>/documents/<int:document_id>/status/",
        views.document_ocr_status,
        name="document-ocr-status",
    ),
    path("portal/", views.parent_portal, name="parent-portal"),
    # P12: ownership-scoped proxy redirect to a stored Invoice Ninja invoice URL.
    path(
        "portal/invoices/<int:invoice_id>/open/",
        views.open_parent_invoice,
        name="parent-invoice-open",
    ),
]
