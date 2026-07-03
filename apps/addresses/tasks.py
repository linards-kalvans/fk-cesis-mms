"""Scheduled VZD address import tasks."""

from __future__ import annotations

import logging

from django.conf import settings

from apps.addresses.services import import_vzd_addresses_from_urls as import_vzd_addresses_from_urls_service

logger = logging.getLogger(__name__)


def import_vzd_addresses_from_urls() -> None:
    region_codes = list(getattr(settings, "ADDRESS_AUTOCOMPLETE_REGION_CODES", []))
    if not region_codes:
        logger.info("address import skipped: ADDRESS_AUTOCOMPLETE_REGION_CODES is empty")
        return
    import_vzd_addresses_from_urls_service(region_codes=region_codes)
