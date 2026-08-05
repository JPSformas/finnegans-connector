"""Gestion de cambios pendientes con confirmacion obligatoria.

Las operaciones de escritura (POST/PUT/DELETE) se preparan primero
y solo se ejecutan cuando el usuario confirma explicitamente.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class ValidationError(Exception):
    """Error en el flujo de validacion."""


WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
READ_METHODS = frozenset({"GET", "HEAD"})


@dataclass
class PendingChange:
    """Operacion de escritura pendiente de confirmacion."""

    confirmacion_id: str
    api_id: str
    metodo: str
    resource_id: str | None
    parametros: dict[str, Any]
    body: Any
    resumen: str
    creado_en: float = field(default_factory=time.time)
    expira_en: float = field(default_factory=lambda: time.time() + 600)


class ChangeStore:
    """Almacen en memoria de cambios pendientes (TTL 10 min)."""

    TTL_SECONDS = 600

    def __init__(self) -> None:
        self._pending: dict[str, PendingChange] = {}

    def _cleanup(self) -> None:
        now = time.time()
        expired = [k for k, v in self._pending.items() if v.expira_en < now]
        for k in expired:
            del self._pending[k]

    def prepare(
        self,
        api_id: str,
        metodo: str,
        resource_id: str | None,
        parametros: dict[str, Any] | None,
        body: Any,
        resumen: str,
    ) -> PendingChange:
        self._cleanup()
        metodo = metodo.upper()
        if metodo not in WRITE_METHODS:
            raise ValidationError(
                f"Metodo '{metodo}' no es de escritura. "
                f"Usa consultar_finnegans para lecturas (GET)."
            )

        confirmacion_id = str(uuid.uuid4())[:8]
        pending = PendingChange(
            confirmacion_id=confirmacion_id,
            api_id=api_id,
            metodo=metodo,
            resource_id=resource_id,
            parametros=parametros or {},
            body=body,
            resumen=resumen,
            expira_en=time.time() + self.TTL_SECONDS,
        )
        self._pending[confirmacion_id] = pending
        return pending

    def consume(self, confirmacion_id: str, usuario_confirmo: bool) -> PendingChange:
        self._cleanup()
        if not usuario_confirmo:
            raise ValidationError(
                "La operacion NO fue ejecutada: el usuario no confirmo. "
                "El lider debe responder explicitamente 'si, confirmo' antes de ejecutar."
            )
        pending = self._pending.get(confirmacion_id)
        if not pending:
            raise ValidationError(
                f"Confirmacion '{confirmacion_id}' no encontrada o expirada. "
                "Volvé a preparar el cambio con preparar_cambio."
            )
        del self._pending[confirmacion_id]
        return pending


_TIPOS_PY = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validar_body(body: dict | None, body_schema: dict | None) -> list[str]:
    """Valida el body propuesto contra el requestBodySchema del endpoint."""
    if body_schema is None:
        return ["(sin schema: no se pudo verificar contra la documentacion)"]
    body = body or {}
    props = body_schema.get("properties", {}) or {}
    requeridos = body_schema.get("required", []) or []
    problemas: list[str] = []

    for req in requeridos:
        if req not in body:
            problemas.append(f"Falta el campo requerido '{req}'.")

    for campo, valor in body.items():
        if campo not in props:
            problemas.append(f"Campo desconocido '{campo}' (no existe en la documentacion).")
            continue
        tipo = props[campo].get("type")
        py = _TIPOS_PY.get(tipo)
        if py and valor is not None and not isinstance(valor, py):
            # bool es subclase de int; evitar falso positivo con number/integer
            if not (tipo in ("integer", "number") and isinstance(valor, bool) is False and isinstance(valor, (int, float))):
                problemas.append(
                    f"Campo '{campo}': se esperaba {tipo}, se recibio {type(valor).__name__}."
                )
    return problemas
