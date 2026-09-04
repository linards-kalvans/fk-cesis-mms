"""Admin list filters keyed on MedicalPermit status (P23).

``MedicalPermitStatusFilter`` is a base ``SimpleListFilter``; concrete
subclasses bind it to the FK that links the filtered model to
``MedicalPermit`` (``application_id`` or ``member_id``). Statuses mirror the
service helper: missing (no permit or no evidence), expiring, expired.
"""

from django.contrib import admin

from apps.documents.medical_permits import medical_permit_status
from apps.documents.models import MedicalPermit


class MedicalPermitStatusFilter(admin.SimpleListFilter):
    """Base filter; subclasses set ``permit_field`` to the linking FK name."""

    parameter_name = "medical_permit_status"
    title = "Veselības apliecība"
    permit_field = "application_id"

    def lookups(self, request, model_admin):
        return (
            ("missing", "Trūkst"),
            ("expiring", "Beidzas"),
            ("expired", "Beidzies"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"missing", "expiring", "expired"}:
            return queryset
        pks = list(queryset.values_list("pk", flat=True))
        permits = {
            getattr(permit, self.permit_field): permit
            for permit in MedicalPermit.objects.filter(
                **{f"{self.permit_field}__in": pks}
            )
        }
        matching = [
            pk
            for pk in pks
            if medical_permit_status(permits.get(pk)) == value
        ]
        return queryset.filter(pk__in=matching)


class RegistrationMedicalPermitStatusFilter(MedicalPermitStatusFilter):
    permit_field = "application_id"


class MemberMedicalPermitStatusFilter(MedicalPermitStatusFilter):
    permit_field = "member_id"