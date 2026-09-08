from django.urls import path

from apps.admin_hub import views

app_name = "admin_hub"

urlpatterns = [
    path("pieteikumi/", views.queue_view, name="queue"),
    path("pieteikumi/<int:pk>/", views.cockpit_view, name="cockpit"),
    path("pieteikumi/<int:pk>/ligums/", views.agreement_view, name="agreement"),
    path("pieteikumi/<int:pk>/rekini/", views.billing_view, name="billing"),
]
