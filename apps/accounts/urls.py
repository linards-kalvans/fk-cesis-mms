"""URLconf for the accounts app."""

from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("request-magic-link/", views.request_magic_link, name="request-magic-link"),
    path("verify/<str:token>/", views.verify_magic_link, name="verify-magic-link"),
    path("logout/", views.logout_view, name="logout"),
    path("register/verify/", views.verify_one_time_code_view, name="verify-one-time-code"),
]
