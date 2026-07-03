"""Shared fixtures for tests/addresses/."""

from __future__ import annotations

from pathlib import Path

import pytest


def write_csv(path: Path, header: str, rows: list[str]) -> Path:
    """Write a minimal VZD-like CSV encoded as ISO-8859-1 (ASCII-safe rows)."""
    path.write_bytes((header + "\n" + "\n".join(rows) + "\n").encode("ISO-8859-1"))
    return path


@pytest.fixture
def vzd_files(tmp_path):
    """Minimal Cesis-area fixture with one apartment row from AW_DZIV.

    One novads (300), one pilseta (200 under 300), one street (100 under 200),
    two active building rows + one DEL row, and one active + one DEL apartment row.
    """
    from apps.addresses.services import VzdAddressFiles

    novads = write_csv(
        tmp_path / "AW_NOVADS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["300,EKS,Cesu nov.,"],
    )
    pagasts = write_csv(
        tmp_path / "AW_PAGASTS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    pilseta = write_csv(
        tmp_path / "AW_PILSETA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["200,EKS,Cesis,300"],
    )
    ciems = write_csv(
        tmp_path / "AW_CIEMS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    iela = write_csv(
        tmp_path / "AW_IELA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["100,EKS,Raina iela,200"],
    )
    eka = write_csv(
        tmp_path / "AW_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        [
            '401,EKS,100,1,"Raina iela 1, Cesis, Cesu nov.",LV-4101,,,,',
            '402,EKS,100,2,"Raina iela 2, Cesis, Cesu nov.",LV-4101,,,,',
            '403,DEL,100,3,"Raina iela 3, Cesis, Cesu nov.",LV-4101,,,,',
        ],
    )
    dziv = write_csv(
        tmp_path / "AW_DZIV.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB",
        [
            '9001,EKS,401,3,"Raina iela 1-3, Cesis, Cesu nov.",LV-4101',
            '9002,DEL,401,4,"Raina iela 1-4, Cesis, Cesu nov.",LV-4101',
        ],
    )
    return VzdAddressFiles(
        novads=novads,
        pagasts=pagasts,
        pilseta=pilseta,
        ciems=ciems,
        iela=iela,
        eka=eka,
        dziv=dziv,
    )
