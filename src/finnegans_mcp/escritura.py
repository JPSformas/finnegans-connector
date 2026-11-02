"""Armado del body de una escritura y resumen de lo que cambio despues.

El PUT de Finnegans reemplaza el registro completo, asi que el body se arma
sobre el JSON crudo que `leer` dejo en el workspace (`base`), cambiando solo
las claves de `cambios`. Despues de escribir se relee el registro y se compara:
la API a veces completa campos por su cuenta.
"""
from __future__ import annotations

import copy
from typing import Any

from finnegans_core.presupuesto import resumir_valor

VALOR_MAX_CHARS = 80
# Espacio que se guarda en cada seccion para la linea "… y N campos más".
_RESERVA_AVISO = 160

TITULO_CAMBIADOS = "Campos cambiados"
TITULO_PROPIOS = "Campos que la API cambió por su cuenta"


def armar_body(body: dict | None, base_crudo: dict | None, cambios: dict | None) -> dict:
    """Body a enviar. Con base + cambios, cada clave de cambios reemplaza su valor entero.

    Nunca modifica `body` ni `base_crudo`: devuelve una copia.
    """
    if body is not None and base_crudo is not None:
        raise ValueError(
            "Pasá body o base, no los dos: body es el registro completo; "
            "base + cambios modifica un registro ya cargado con leer."
        )
    if base_crudo is not None:
        if not cambios:
            raise ValueError(
                "Con base hay que pasar cambios: los campos a modificar y su valor nuevo."
            )
        salida = copy.deepcopy(base_crudo)
        salida.update(copy.deepcopy(cambios))
        return salida
    if cambios:
        raise ValueError(
            "cambios solo se usa junto con base: cargá el registro con leer y pasá "
            "esa tabla como base, o mandá el registro completo en body."
        )
    return copy.deepcopy(body) if body is not None else {}


def _corto(v: Any) -> str:
    if v is None:
        return "(vacío)"
    texto = resumir_valor(v, VALOR_MAX_CHARS)
    return texto if texto else '""'


def _vacio(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _claves(*dicts: dict) -> list[str]:
    vistas: dict[str, None] = {}
    for d in dicts:
        for k in d:
            vistas.setdefault(k, None)
    return list(vistas)


def _acotar(lineas: list[str], max_chars: int | None) -> list[str]:
    """Las lineas que entran en max_chars; si sobran, una linea que dice cuantas."""
    if max_chars is None:
        return lineas
    salida: list[str] = []
    usado = 0
    for i, linea in enumerate(lineas):
        if usado + len(linea) + 1 > max_chars - _RESERVA_AVISO:
            salida.append(
                f"- … y {len(lineas) - i} campos más que no entran en el chat "
                "(para verlos, leé el registro completo con leer y consultá la tabla)"
            )
            break
        salida.append(linea)
        usado += len(linea) + 1
    return salida


def diff(antes: dict | None, enviado: dict, despues: dict,
         max_chars: int | None = None) -> str:
    """Resumen compacto: que cambio (antes → despues) y que cambio la API sola.

    "Por su cuenta" es todo campo cuyo valor releido difiere de lo enviado.
    Un campo que no se mando y vuelve vacio no cuenta: la API lista todos sus
    campos aunque esten en blanco. Con `max_chars`, cada seccion usa a lo sumo
    la mitad y dice cuantos campos quedaron afuera.
    """
    mitad = None if max_chars is None else max_chars // 2
    lineas = [f"{TITULO_CAMBIADOS} (antes → después):"]
    if antes is None:
        lineas.append(
            "- (no hay estado previo para comparar: se escribió sin base. Para ver el "
            "antes y el después, cargá el registro con leer y usá base + cambios.)"
        )
    else:
        faltan = object()
        cambiados = [
            k for k in _claves(antes, despues)
            if antes.get(k, faltan) != despues.get(k, faltan)
        ]
        if cambiados:
            lineas += _acotar([
                f"- {k}: {_corto(antes.get(k))} → {_corto(despues.get(k))}"
                for k in cambiados
            ], mitad)
        else:
            lineas.append("- (ninguno)")

    lineas.append("")
    lineas.append(f"{TITULO_PROPIOS} (enviado → quedó):")
    propios: list[str] = []
    for k in _claves(enviado, despues):
        if k not in enviado:
            if not _vacio(despues.get(k)):
                propios.append(f"- {k}: (no enviado) → {_corto(despues.get(k))}")
        elif k not in despues:
            propios.append(f"- {k}: {_corto(enviado[k])} → (no vino en la relectura)")
        elif enviado[k] != despues[k]:
            propios.append(f"- {k}: {_corto(enviado[k])} → {_corto(despues[k])}")
    lineas += _acotar(propios, mitad) if propios else ["- (ninguno)"]
    return "\n".join(lineas)
