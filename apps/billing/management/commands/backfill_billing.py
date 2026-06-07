"""Create draft BillingRecords for already-signed agreements that lack one."""

from django.core.management.base import BaseCommand

from apps.agreements.models import Agreement
from apps.billing.services import create_draft_billing_for_member


class Command(BaseCommand):
    help = "Backfill draft billing records for signed agreements without one."

    def handle(self, *args, **options):
        created = 0
        seen_members = set()
        signed = (
            Agreement.objects.filter(state=Agreement.State.SIGNED)
            .select_related("member")
            .order_by("pk")
        )
        for agreement in signed:
            if agreement.member_id in seen_members:
                continue
            seen_members.add(agreement.member_id)
            record = create_draft_billing_for_member(agreement.member, agreement=agreement)
            if record is not None and record.agreement_id == agreement.pk:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Backfill complete: {created} created."))
