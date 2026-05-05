"""URL routing for registration workflow."""

from django.urls import path

from apps.registrations import views

app_name = "registrations"

urlpatterns = [
    path("register/", views.start_registration, name="start-registration"),
    path("applications/<int:application_id>/edit/", views.edit_registration, name="edit-registration"),
    path("applications/<int:application_id>/submit/", views.submit_registration, name="submit-registration"),
    path("portal/", views.parent_portal, name="parent-portal"),
]
