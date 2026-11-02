"""Exporta un resultado tabular a xlsx o csv sin pisar archivos existentes."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font

_PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}


def _nombre_seguro(nombre: str, formato: str) -> str:
    base = _PROHIBIDOS.sub("_", nombre or "").strip().rstrip(". ")
    if base.lower().endswith(f".{formato}"):
        base = base[: -(len(formato) + 1)].rstrip(". ")
    if not base:
        base = "exportacion"
    if base.split(".")[0].upper() in _RESERVADOS:
        base = f"_{base}"
    return base


_NATIVOS = (str, int, float, bool, Decimal, date, datetime, time, timedelta)


def _valor(v: Any) -> Any:
    """Valor apto para xlsx y csv.

    dict/list van como JSON; fechas con zona como texto ISO (Excel no las
    soporta); cualquier otro tipo no nativo (UUID, bytes, ...) como str().
    Se sacan los caracteres de control que Excel no admite.
    """
    if v is None:
        return None
    if isinstance(v, (dict, list, tuple)):
        v = json.dumps(v, ensure_ascii=False, default=str)
    elif isinstance(v, (datetime, time)) and v.tzinfo is not None:
        v = v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    elif not isinstance(v, _NATIVOS):
        v = str(v)
    if isinstance(v, str):
        v = ILLEGAL_CHARACTERS_RE.sub("", v)
    return v


def _destino(carpeta: Path, base: str, formato: str) -> Path:
    ruta = carpeta / f"{base}.{formato}"
    n = 2
    while ruta.exists():
        ruta = carpeta / f"{base} ({n}).{formato}"
        n += 1
    return ruta


def _escribir_xlsx(columnas: list[str], filas: list[tuple], ruta: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append([str(c) for c in columnas])
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for fila in filas:
        fila_xl = []
        for v in fila:
            fila_xl.append(_valor(v))
        ws.append(fila_xl)
        # Un texto que empieza con "=" es dato del cliente, no una formula.
        for c in ws[ws.max_row]:
            if isinstance(c.value, str) and c.value.startswith("="):
                c.data_type = "s"
    wb.save(ruta)


def _escribir_csv(columnas: list[str], filas: list[tuple], ruta: Path) -> None:
    # "x" falla si el archivo aparecio entre el chequeo y la escritura.
    with open(ruta, "x", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([str(c) for c in columnas])
        for fila in filas:
            w.writerow(["" if v is None else _valor(v) for v in fila])


def exportar(
    columnas: list[str],
    filas: list[tuple],
    carpeta: Path,
    nombre: str,
    formato: Literal["xlsx", "csv"],
) -> Path:
    """Escribe el archivo en `carpeta` (se crea si falta) y devuelve su ruta.

    Nunca sobrescribe: si existe agrega ' (2)', ' (3)', ... al nombre.
    El csv sale en UTF-8 con BOM para que Excel respete tildes y ñ.
    """
    if formato not in ("xlsx", "csv"):
        raise ValueError(f"Formato no soportado: {formato!r}. Use 'xlsx' o 'csv'.")
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = _destino(carpeta, _nombre_seguro(nombre, formato), formato)
    if formato == "xlsx":
        _escribir_xlsx(columnas, filas, ruta)
    else:
        _escribir_csv(columnas, filas, ruta)
    return ruta
