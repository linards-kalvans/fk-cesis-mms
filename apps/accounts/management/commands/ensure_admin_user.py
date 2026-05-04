"""Ensure an admin superuser exists based on env vars.

Env vars:
    DJANGO_SUPERUSER_EMAIL (required)
    DJANGO_SUPERUSER_PASSWORD (required)
    DJANGO_SUPERUSER_USERNAME (optional, defaults to email)
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Create or update a superuser from env vars."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write(self.style.WARNING("Missing env vars — no user created."))
            return

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", email)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        user.is_staff = True
        user.is_superuser = True
        user.email = email
        user.set_password(password)
        user.save(update_fields=["password", "is_staff", "is_superuser", "email"])

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} superuser '{username}'."))
