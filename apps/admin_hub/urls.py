from django.urls import path

from apps.admin_hub import views

app_name = "admin_hub"

urlpatterns = [
    path("pieteikumi/", views.queue_view, name="queue"),
]
