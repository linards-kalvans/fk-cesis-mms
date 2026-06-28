"""VZD address import, normalization, and grouped search services."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from apps.addresses.models import AddressEntry, AddressGroup, AddressImportRun


def normalize_address_query(value: str) -> str:
    """Lowercase, strip Latvian diacritics and punctuation, and collapse whitespace."""
    text = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    ascii_text = re.sub(r"[^\w\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _has_house_token(normalized: str) -> bool:
    return any(re.search(r"\d", token) for token in normalized.split())


def _numeric_tokens(normalized: str) -> list[str]:
    return [token for token in normalized.split() if token.isdigit()]


def _house_number_token(label: str) -> str | None:
    """Return the first number-like token from the label (the building number)."""
    for token in normalize_address_query(label).split():
        if re.search(r"\d", token):
            return token
    return None


def _entry_results(
    filters: Q, normalized: str, limit: int, *, require_house_match: bool = False
) -> list[dict[str, str]]:
    token_filters = filters
    for token in normalized.split():
        token_filters &= Q(normalized_label__icontains=token)
    qs = (
        AddressEntry.objects.filter(token_filters)
        .annotate(
            rank=Case(
                When(normalized_label__startswith=normalized, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("rank", "normalized_label")
        .values("id", "label", "normalized_label", "postal_code", "region_name", "rank")
    )
    numeric_tokens = _numeric_tokens(normalized)
    # ponytail: numeric address search filters house numbers in Python; use
    # PostgreSQL trigram/ranked search if nationwide imports make this slow.
    if not numeric_tokens:
        qs = qs[:limit]
    rows = [
        {
            "kind": "address",
            "id": str(row["id"]),
            "label": row["label"],
            "normalized_label": row["normalized_label"],
            "hint": row["postal_code"] or row["region_name"] or "",
            "rank": row["rank"],
        }
        for row in qs
    ]
    if numeric_tokens:
        kept: list[dict[str, object]] = []
        for row in rows:
            house = _house_number_token(row["label"])
            house_match = house is not None and any(house.startswith(num) for num in numeric_tokens)
            if require_house_match and not house_match:
                continue
            row["house_match"] = house_match
            kept.append(row)
        rows = kept
        if not require_house_match:
            rows.sort(key=lambda r: (not r["house_match"], r["rank"], r["normalized_label"]))
    return [
        {"kind": row["kind"], "id": row["id"], "label": row["label"], "hint": row["hint"]}
        for row in rows[:limit]
    ]


@dataclass(frozen=True)
class VzdAddressFiles:
    novads: Path
    pagasts: Path
    pilseta: Path
    ciems: Path
    iela: Path
    eka: Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "ISO-8859-1"):
        try:
            with path.open(encoding=encoding, newline="") as f:
                reader = csv.DictReader(f, delimiter=",")
                return [row for row in reader]
        except UnicodeDecodeError:
            continue
    return []


def _active_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("STATUSS", "").strip().upper() == "EKS"]


def import_vzd_addresses(files: VzdAddressFiles, region_codes: list[str]) -> AddressImportRun:
    """Parse local VZD CSV files and replace the address index atomically."""
    run: AddressImportRun = AddressImportRun.objects.create(
        source="vzd_varis",
        region_codes=",".join(region_codes),
    )
    region_set = set(region_codes)

    try:
        novads_rows = _active_rows(_read_csv(files.novads))
        pagasts_rows = _active_rows(_read_csv(files.pagasts))
        pilseta_rows = _active_rows(_read_csv(files.pilseta))
        ciems_rows = _active_rows(_read_csv(files.ciems))
        iela_rows = _active_rows(_read_csv(files.iela))
        eka_rows = _active_rows(_read_csv(files.eka))
    except Exception as exc:  # noqa: BLE001
        run.status = AddressImportRun.Status.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return run

    novads_names = {row["KODS"].strip(): row["NOSAUKUMS"].strip() for row in novads_rows}
    pagasts_map = {
        row["KODS"].strip(): {"name": row["NOSAUKUMS"].strip(), "parent_code": row["VKUR_CD"].strip()}
        for row in pagasts_rows
    }
    pilseta_map = {
        row["KODS"].strip(): {"name": row["NOSAUKUMS"].strip(), "parent_code": row["VKUR_CD"].strip()}
        for row in pilseta_rows
    }
    ciems_map = {
        row["KODS"].strip(): {"name": row["NOSAUKUMS"].strip(), "parent_code": row["VKUR_CD"].strip()}
        for row in ciems_rows
    }

    locality_map: dict[str, dict[str, str]] = {}
    for row in pilseta_rows + pagasts_rows + ciems_rows:
        code = row["KODS"].strip()
        name = row["NOSAUKUMS"].strip()
        parent_code = row["VKUR_CD"].strip()
        # State cities (Rīga, Daugavpils, etc.) hang directly off the root.
        # Treat them as their own import region so operators can include them
        # without importing every root-level city at once.
        if parent_code == "100000000":
            region_code = code
            novads_names.setdefault(code, name)
            parent_name = ""
        elif parent_code in novads_names:
            region_code = parent_code
            parent_name = ""
        elif parent_code in pagasts_map:
            region_code = pagasts_map[parent_code]["parent_code"]
            parent_name = pagasts_map[parent_code]["name"]
        else:
            region_code = parent_code
            parent_name = ""
        kind = "city" if row in pilseta_rows else "parish" if row in pagasts_rows else "village"
        locality_map[code] = {
            "name": name,
            "region_code": region_code,
            "parent_code": parent_code,
            "parent_name": parent_name,
            "kind": kind,
        }

    iela_map: dict[str, dict[str, str]] = {}
    for row in iela_rows:
        iela_map[row["KODS"].strip()] = {
            "name": row["NOSAUKUMS"].strip(),
            "locality_code": row["VKUR_CD"].strip(),
        }

    groups: dict[tuple[str, str, str], AddressGroup] = {}
    entries: list[AddressEntry] = []

    for row in eka_rows:
        vkur_cd = row["VKUR_CD"].strip()
        street = iela_map.get(vkur_cd)
        locality = None
        if street:
            locality = locality_map.get(street["locality_code"])
            region_code = locality["region_code"] if locality else ""
            if region_set and region_code not in region_set:
                continue
            street_name = street["name"]
            locality_name = locality["name"] if locality else ""
            region_name = novads_names.get(region_code, "")
            group_key = (street_name, locality_name, region_code)
            street_code = vkur_cd
            locality_code = street["locality_code"]
            group_label = f"{street_name}, {locality_name}" if locality_name else street_name
        else:
            locality = locality_map.get(vkur_cd)
            if not locality:
                continue
            region_code = locality["region_code"]
            if region_set and region_code not in region_set:
                continue
            street_name = ""
            locality_name = locality["name"]
            region_name = novads_names.get(region_code, "")
            group_key = ("", locality_name, region_code)
            street_code = ""
            locality_code = vkur_cd
            parent_name = locality.get("parent_name", "")
            group_label = f"{locality_name}, {parent_name}" if parent_name else locality_name

        if group_key not in groups:
            groups[group_key] = AddressGroup(
                label=group_label,
                normalized_label=normalize_address_query(group_label),
                street_code=street_code,
                street_name=street_name,
                locality_code=locality_code,
                locality_name=locality_name,
                region_code=region_code,
                region_name=region_name,
            )

        entry_label = row["STD"].strip().strip('"')
        entries.append(
            AddressEntry(
                vzd_code=row["KODS"].strip(),
                label=entry_label,
                normalized_label=normalize_address_query(entry_label),
                group=groups[group_key],
                postal_code=row.get("ATRIB", "").strip(),
                region_code=region_code,
                region_name=region_name,
                koord_x=row.get("KOORD_X", "").strip(),
                koord_y=row.get("KOORD_Y", "").strip(),
                dd_n=row.get("DD_N", "").strip(),
                dd_e=row.get("DD_E", "").strip(),
            )
        )

    with transaction.atomic():
        AddressGroup.objects.all().delete()
        for group in groups.values():
            group.entry_count = 0
        saved_groups = list(groups.values())
        for group in saved_groups:
            group.save()

        for entry in entries:
            entry.group_id = entry.group.id
        AddressEntry.objects.bulk_create(entries)

        # Refresh per-group counts
        for group in saved_groups:
            group.entry_count = group.entries.count()
            group.save(update_fields=["entry_count"])

    run.status = AddressImportRun.Status.SUCCEEDED
    run.group_count = len(saved_groups)
    run.entry_count = len(entries)
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "group_count", "entry_count", "finished_at"])
    return run


def _group_results(normalized: str, limit: int) -> list[dict[str, str]]:
    qs = (
        AddressGroup.objects.filter(normalized_label__icontains=normalized)
        .annotate(
            rank=Case(
                When(normalized_label__startswith=normalized, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("rank", "normalized_label")
        .values("id", "label", "region_name")[:limit]
    )
    return [
        {
            "kind": "group",
            "id": str(row["id"]),
            "label": row["label"],
            "hint": row["region_name"] or "",
        }
        for row in qs
    ]


def search_addresses(query: str, group_id: int | None = None, limit: int = 10) -> list[dict[str, str]]:
    """Return grouped address suggestions for the given query."""
    normalized = normalize_address_query(query)

    if group_id is not None:
        return _entry_results(Q(group_id=group_id), normalized, limit, require_house_match=True)

    if len(normalized) < 3:
        return []

    if _has_house_token(normalized):
        entries = _entry_results(Q(), normalized, limit)
        if len(entries) >= limit:
            return entries
        return entries + _group_results(normalized, limit - len(entries))

    return _group_results(normalized, limit)
