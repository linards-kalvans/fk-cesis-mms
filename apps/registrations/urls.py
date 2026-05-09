"""URL routing for registration workflow."""

from django.urls import path

from apps.registrations import views

app_name = "registrations"

urlpatterns = [
    path("applications/new/", views.new_application, name="new-application"),
    path("register/", views.start_registration, name="start-registration"),
    path("applications/<int:application_id>/edit/", views.edit_registration, name="edit-registration"),
    path("applications/<int:application_id>/submit/", views.submit_registration, name="submit-registration"),
    path("applications/<int:application_id>/summary/", views.view_registration_summary, name="view-registration-summary"),
    path("applications/<int:application_id>/detail/", views.view_registration_detail, name="view-registration-detail"),
    path("portal/", views.parent_portal, name="parent-portal"),
    # Staff review
    path("admin/review/applications/", views.admin_review_queue, name="admin-review-queue"),
    path("admin/review/applications/<int:application_id>/", views.admin_review_detail, name="admin-review-detail"),
]
