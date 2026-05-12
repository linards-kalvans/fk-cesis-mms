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
    path("portal/", views.parent_portal, name="parent-portal"),
    # Staff review
    path("admin/review/applications/", views.admin_review_queue, name="admin-review-queue"),
    path("admin/review/applications/<int:application_id>/", views.admin_review_detail, name="admin-review-detail"),
]
