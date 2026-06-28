"""Import VZD address register CSV files into the local autocomplete index."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.addresses.models import AddressImportRun
from apps.addresses.services import VzdAddressFiles, import_vzd_addresses


class Command(BaseCommand):
    help = "Import local VZD address CSV files for autocomplete."

    def add_arguments(self, parser):
        parser.add_argument("--novads", type=Path, required=True)
        parser.add_argument("--pagasts", type=Path, required=True)
        parser.add_argument("--pilseta", type=Path, required=True)
        parser.add_argument("--ciems", type=Path, required=True)
        parser.add_argument("--iela", type=Path, required=True)
        parser.add_argument("--eka", type=Path, required=True)
        parser.add_argument(
            "--region-code",
            action="append",
            default=None,
            help="Region/locality object code to import (repeatable). "
            "Defaults to ADDRESS_AUTOCOMPLETE_REGION_CODES if omitted.",
        )

    def handle(self, *args, **options):
        files = VzdAddressFiles(
            novads=Path(options["novads"]),
            pagasts=Path(options["pagasts"]),
            pilseta=Path(options["pilseta"]),
            ciems=Path(options["ciems"]),
            iela=Path(options["iela"]),
            eka=Path(options["eka"]),
        )
        region_codes = options["region_code"]
        if region_codes is None:
            region_codes = settings.ADDRESS_AUTOCOMPLETE_REGION_CODES
        if not region_codes:
            raise CommandError(
                "No region codes configured. Use --region-code or set ADDRESS_AUTOCOMPLETE_REGION_CODES."
            )

        run = import_vzd_addresses(files, region_codes=region_codes)
        if run.status == AddressImportRun.Status.FAILED:
            raise CommandError(f"Address import failed: {run.error_message}")
        self.stdout.write(
            f"Imported {run.group_count} address groups and {run.entry_count} address entries."
        )
