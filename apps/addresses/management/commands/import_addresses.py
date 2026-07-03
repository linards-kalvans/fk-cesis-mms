"""Import VZD address register CSV files into the local autocomplete index."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.addresses.models import AddressImportRun
from apps.addresses.services import VzdAddressFiles, download_vzd_address_files, import_vzd_addresses


class Command(BaseCommand):
    help = "Import local VZD address CSV files for autocomplete."

    def add_arguments(self, parser):
        parser.add_argument("--novads", type=Path, required=False)
        parser.add_argument("--pagasts", type=Path, required=False)
        parser.add_argument("--pilseta", type=Path, required=False)
        parser.add_argument("--ciems", type=Path, required=False)
        parser.add_argument("--iela", type=Path, required=False)
        parser.add_argument("--eka", type=Path, required=False)
        parser.add_argument("--dziv", type=Path, required=False)
        parser.add_argument(
            "--region-code",
            action="append",
            default=None,
            help="Region/locality object code to import (repeatable). "
            "Defaults to ADDRESS_AUTOCOMPLETE_REGION_CODES if omitted.",
        )

    def handle(self, *args, **options):
        region_codes = options["region_code"]
        if region_codes is None:
            region_codes = settings.ADDRESS_AUTOCOMPLETE_REGION_CODES
        if not region_codes:
            raise CommandError(
                "No region codes configured. Use --region-code or set ADDRESS_AUTOCOMPLETE_REGION_CODES."
            )

        file_names = ("novads", "pagasts", "pilseta", "ciems", "iela", "eka", "dziv")
        downloaded: VzdAddressFiles | None = None
        if not all(options[name] for name in file_names):
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    downloaded = download_vzd_address_files(Path(tmp))
                    files = VzdAddressFiles(
                        novads=Path(options["novads"]) if options["novads"] else downloaded.novads,
                        pagasts=Path(options["pagasts"]) if options["pagasts"] else downloaded.pagasts,
                        pilseta=Path(options["pilseta"]) if options["pilseta"] else downloaded.pilseta,
                        ciems=Path(options["ciems"]) if options["ciems"] else downloaded.ciems,
                        iela=Path(options["iela"]) if options["iela"] else downloaded.iela,
                        eka=Path(options["eka"]) if options["eka"] else downloaded.eka,
                        dziv=Path(options["dziv"]) if options["dziv"] else downloaded.dziv,
                    )
                    run = import_vzd_addresses(files, region_codes=region_codes)
                    if run.status == AddressImportRun.Status.FAILED:
                        raise CommandError(f"Address import failed: {run.error_message}")
                    self.stdout.write(
                        f"Imported {run.group_count} address groups and {run.entry_count} address entries."
                    )
                    return
            except CommandError:
                raise
            except Exception as exc:  # noqa: BLE001
                AddressImportRun.objects.create(
                    source="vzd_varis",
                    region_codes=",".join(region_codes),
                    status=AddressImportRun.Status.FAILED,
                    error_message=str(exc),
                    finished_at=timezone.now(),
                )
                raise CommandError(f"Address import failed: {exc}")

        files = VzdAddressFiles(
            novads=Path(options["novads"]),
            pagasts=Path(options["pagasts"]),
            pilseta=Path(options["pilseta"]),
            ciems=Path(options["ciems"]),
            iela=Path(options["iela"]),
            eka=Path(options["eka"]),
            dziv=Path(options["dziv"]),
        )
        run = import_vzd_addresses(files, region_codes=region_codes)
        if run.status == AddressImportRun.Status.FAILED:
            raise CommandError(f"Address import failed: {run.error_message}")
        self.stdout.write(
            f"Imported {run.group_count} address groups and {run.entry_count} address entries."
        )
