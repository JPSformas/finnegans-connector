"""Redaccion compartida de valores sensibles (tokens, secretos, passwords).

Solo libreria estandar. Usado por el log de auditoria y por la vista previa
de cambios para nunca mostrar ni persistir credenciales en claro.
"""
from __future__ import annotations

from typing import Any

SENSIBLE = ("access_token", "token", "secret", "password", "client_secret")


def es_clave_sensible(clave: Any) -> bool:
    """True si la clave contiene algun termino sensible (comparacion por substring)."""
    clave_lower = str(clave).lower()
    return any(s in clave_lower for s in SENSIBLE)


def redactar(value: Any) -> Any:
    """Redacta recursivamente valores sensibles.

    - dicts: enmascara ('***') el valor de las claves sensibles, recurre en el resto.
    - listas/tuplas: recurre en cada elemento (devuelve siempre una lista).
    - cualquier otro valor: se devuelve sin cambios.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            out[k] = "***" if es_clave_sensible(k) else redactar(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redactar(v) for v in value]
    return value
