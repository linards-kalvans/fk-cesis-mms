"""Django admin for members app."""

from django.contrib import admin

from apps.members.models import Guardian, Member, TrainingGroup


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone")
    search_fields = ("full_name", "email", "personal_id")


@admin.register(TrainingGroup)
class TrainingGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "guardian", "birth_date", "training_group")
    list_filter = ("training_group",)
    search_fields = ("full_name", "personal_id")
