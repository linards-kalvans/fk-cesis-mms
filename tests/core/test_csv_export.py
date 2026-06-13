"""csv_response — UTF-8 BOM + semicolon CSV with value formatting + injection guard."""

import csv
import datetime
import io

from apps.core.export import csv_response


def _parse(resp):
    body = resp.content.decode("utf-8")
    assert body.startswith("﻿")  # UTF-8 BOM
    reader = csv.reader(io.StringIO(body[1:]), delimiter=";")
    return list(reader)


def test_header_and_delimiter_and_bom():
    resp = csv_response(filename="x.csv", columns=["A", "B"], rows=[["1", "2"]])
    assert resp["Content-Type"].startswith("text/csv")
    assert 'attachment; filename="x.csv"' in resp["Content-Disposition"]
    rows = _parse(resp)
    assert rows[0] == ["A", "B"]
    assert rows[1] == ["1", "2"]


def test_value_formatting():
    resp = csv_response(
        filename="x.csv",
        columns=["a", "b", "c", "d"],
        rows=[[None, True, False, datetime.date(2026, 9, 20)]],
    )
    assert _parse(resp)[1] == ["", "jā", "nē", "2026-09-20"]


def test_datetime_formatting():
    resp = csv_response(
        filename="x.csv",
        columns=["ts"],
        rows=[[datetime.datetime(2026, 9, 20, 14, 30, 5)]],
    )
    assert _parse(resp)[1] == ["2026-09-20 14:30"]


def test_formula_injection_guard():
    resp = csv_response(filename="x.csv", columns=["a"], rows=[["=SUM(A1:A2)"], ["+1"], ["@x"], ["-3"], ["safe"]])
    data = _parse(resp)
    assert data[1] == ["'=SUM(A1:A2)"]
    assert data[2] == ["'+1"]
    assert data[3] == ["'@x"]
    assert data[4] == ["'-3"]
    assert data[5] == ["safe"]
