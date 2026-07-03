"""CSV export helper — UTF-8 BOM + semicolon delimiter for Latvian Excel,
with value formatting and a spreadsheet formula-injection guard."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Iterable, Sequence
from typing import Any

from django.http import HttpResponse

_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _format(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "jā" if value else "nē"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _guard(text: str) -> str:
    if text and text[0] in _INJECTION_PREFIXES:
        return "'" + text
    return text


def csv_response(*, filename: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> HttpResponse:
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Latvian Excel detects UTF-8
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_guard(_format(cell)) for cell in row])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
