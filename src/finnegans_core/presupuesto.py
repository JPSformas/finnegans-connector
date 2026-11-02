"""Presupuesto de respuesta: cuanto texto le llega a Claude por llamada.

Los resultados grandes de Finnegans viven en el Workspace (DuckDB); al chat
solo van paginas chicas. Este modulo arma esas paginas (tablas markdown que
nunca cortan una celda) y los nombres de tabla. Solo libreria estandar.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

# Tope de caracteres de cualquier respuesta de herramienta hacia el chat.
RESPUESTA_MAX_CHARS = 8000


def _texto(v: Any) -> str:
    """Valor -> texto plano. None es vacio; dict/list salen como JSON."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def _celda(v: Any) -> str:
    """Texto seguro para una celda markdown (sin cortar nada)."""
    return _texto(v).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def resumir_valor(v: Any, max_len: int = 120) -> str:
    """Valor acortado con `…` si es largo. Solo para filas de muestra."""
    s = _texto(v).replace("\r", " ").replace("\n", " ")
    if len(s) > max_len:
        return s[: max(max_len - 1, 0)] + "…"
    return s


def formatear_tabla(
    columnas: list[str], filas: list[tuple], max_chars: int
) -> tuple[str, int]:
    """Tabla markdown con tantas filas como entren en `max_chars`.

    Devuelve (texto, cantidad_de_filas_incluidas). Siempre incluye al menos
    una fila (si hay) aunque se pase del tope: una celda nunca se corta.
    """
    cab = "| " + " | ".join(_celda(c) for c in columnas) + " |"
    sep = "|" + "|".join(" --- " for _ in columnas) + "|"
    lineas = [cab, sep]
    largo = len(cab) + 1 + len(sep)
    n = 0
    for fila in filas:
        linea = "| " + " | ".join(_celda(c) for c in fila) + " |"
        if n >= 1 and largo + 1 + len(linea) > max_chars:
            break
        lineas.append(linea)
        largo += 1 + len(linea)
        n += 1
    return "\n".join(lineas), n


# Palabras que DuckDB 2.0 no deja usar sin comillas como nombre de tabla
# (categorias reserved y type_function de duckdb_keywords()). Un test verifica
# que siga cubriendo la version instalada.
PALABRAS_RESERVADAS = frozenset(
    {
        'all', 'analyse', 'analyze', 'and', 'anti', 'any', 'array', 'as',
        'asc', 'asof', 'asymmetric', 'at', 'authorization', 'binary', 'both',
        'by', 'case', 'cast', 'check', 'collate', 'collation', 'column',
        'columns', 'concurrently', 'constraint', 'create', 'cross', 'default',
        'deferrable', 'desc', 'describe', 'distinct', 'do', 'else', 'end',
        'except', 'false', 'fetch', 'for', 'foreign', 'freeze', 'from',
        'full', 'generated', 'glob', 'group', 'having', 'ilike', 'in',
        'initially', 'inner', 'intersect', 'into', 'is', 'isnull', 'join',
        'lambda', 'lateral', 'leading', 'left', 'like', 'limit', 'map',
        'natural', 'not', 'notnull', 'null', 'offset', 'on', 'only', 'or',
        'order', 'outer', 'overlaps', 'pivot', 'pivot_longer', 'pivot_wider',
        'placing', 'positional', 'primary', 'qualify', 'references',
        'returning', 'right', 'select', 'semi', 'show', 'similar', 'some',
        'struct', 'summarize', 'symmetric', 'table', 'tablesample', 'then',
        'to', 'trailing', 'true', 'try_cast', 'tuple', 'union', 'unique',
        'unpack', 'unpivot', 'using', 'variadic', 'verbose', 'when', 'where',
        'window', 'with'
    }
)


def _limpiar(texto: str) -> str:
    sin_acentos = "".join(
        c
        for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    s = re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower())
    return s.strip("_")


def nombre_tabla(path: str, id: str | None = None) -> str:
    """Nombre de tabla DuckDB a partir del path de la API: [a-z0-9_].

    'reports/ACOrdenesCompraPendientes' -> 'acordenescomprapendientes'
    'cliente/list' -> 'cliente'; ('cliente', 'P-01093') -> 'cliente_p_01093'.
    Una palabra reservada de SQL recibe sufijo: 'order' -> 'order_t'.
    """
    partes = [p for p in (path or "").split("/") if p.strip()]
    if len(partes) > 1 and partes[-1].strip().lower() == "list":
        partes.pop()
    nombre = _limpiar(partes[-1]) if partes else ""
    nombre = nombre or "tabla"
    if id:
        sufijo = _limpiar(str(id))
        if sufijo:
            nombre = f"{nombre}_{sufijo}"
    if nombre[0].isdigit():
        nombre = f"t_{nombre}"
    if nombre in PALABRAS_RESERVADAS:
        nombre = f"{nombre}_t"
    return nombre
