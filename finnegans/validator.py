"""Gestion de cambios pendientes con confirmacion obligatoria.

Las operaciones de escritura (POST/PUT/DELETE) se preparan primero
y solo se ejecutan cuando el usuario confirma explicitamente.
"""
from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .redaction import es_clave_sensible


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
    codigo: str = ""
    preview: str = ""
    alto_riesgo: bool = False
    intentos: int = 0
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
        codigo: str = "",
        preview: str = "",
        alto_riesgo: bool = False,
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
            codigo=codigo,
            preview=preview,
            alto_riesgo=alto_riesgo,
            expira_en=time.time() + self.TTL_SECONDS,
        )
        self._pending[confirmacion_id] = pending
        return pending

    def consume(self, confirmacion_id: str, codigo_tipeado: str) -> PendingChange:
        self._cleanup()
        pending = self._pending.get(confirmacion_id)
        if not pending:
            raise ValidationError(
                f"Confirmacion '{confirmacion_id}' no encontrada o expirada. "
                "Volve a preparar el cambio con preparar_cambio."
            )
        if str(codigo_tipeado).strip() != pending.codigo:
            pending.intentos += 1
            if pending.intentos >= 3:
                del self._pending[confirmacion_id]
                raise ValidationError(
                    "Codigo de confirmacion incorrecto por tercera vez. La operacion "
                    "se INVALIDO por seguridad. Volve a preparar el cambio con preparar_cambio."
                )
            raise ValidationError(
                "Codigo de confirmacion incorrecto. La operacion NO se ejecuto. "
                "Pedile al usuario que tipee exactamente el codigo mostrado en el resumen."
            )
        del self._pending[confirmacion_id]
        return pending


def generar_codigo() -> str:
    """Codigo corto de confirmacion (4 digitos) que el humano debe tipear."""
    return f"{secrets.randbelow(10000):04d}"


def construir_preview(
    api_id: str,
    metodo: str,
    resource_id: str | None,
    parametros: dict | None,
    body: dict | None,
    campos_body: list[str],
    problemas: list[str],
    alto_riesgo: bool,
    motivo: str,
    codigo: str,
) -> str:
    """Arma la vista previa estructurada, campo por campo, para el usuario."""
    lineas = ["=== CONFIRMACION DE CAMBIO ==="]
    if alto_riesgo:
        lineas.append(f"⚠️  ALTO RIESGO: {motivo}")
    lineas.append(f"Operacion: {metodo}  |  Endpoint: {api_id}")
    if resource_id:
        lineas.append(f"Registro afectado (id): {resource_id}")

    if parametros:
        lineas.append("Parametros:")
        for k, v in parametros.items():
            if k == "ACCESS_TOKEN":
                continue
            valor = "***" if es_clave_sensible(k) else v
            lineas.append(f"  - {k}: {valor}")

    if body:
        lineas.append("Datos a enviar:")
        for k, v in body.items():
            marca = "" if (not campos_body or k in campos_body) else "  ⚠️ (campo no documentado)"
            valor = "***" if es_clave_sensible(k) else v
            lineas.append(f"  - {k}: {valor}{marca}")

    if problemas:
        lineas.append("Advertencias de validacion:")
        for p in problemas:
            lineas.append(f"  ⚠️ {p}")

    lineas.append("")
    lineas.append(f"Para EJECUTAR, el usuario debe tipear este codigo: {codigo}")
    return "\n".join(lineas)


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
        if not isinstance(props[campo], dict):
            # Entrada de propiedad malformada en el schema: no se puede verificar tipo.
            continue
        tipo = props[campo].get("type")
        py = _TIPOS_PY.get(tipo)
        if py is None or valor is None:
            continue
        # bool NO es un numero valido en este dominio, aunque en Python sea subclase de int.
        if tipo in ("integer", "number") and isinstance(valor, bool):
            problemas.append(f"Campo '{campo}': se esperaba {tipo}, se recibio bool.")
            continue
        if not isinstance(valor, py):
            problemas.append(
                f"Campo '{campo}': se esperaba {tipo}, se recibio {type(valor).__name__}."
            )
    return problemas


def evaluar_riesgo(
    metodo: str,
    resource_id: str | None,
    api_id: str,
    allow_delete: bool,
    high_risk_patterns: list[str],
) -> tuple[bool, bool, str]:
    """Determina si una escritura esta bloqueada o es de alto riesgo.

    Retorna (bloqueado, alto_riesgo, motivo).
    """
    metodo = metodo.upper()
    motivos: list[str] = []
    alto = False

    if metodo == "DELETE":
        if not allow_delete:
            return (True, True, "Operacion DELETE bloqueada por politica (FINNEGANS_ALLOW_DELETE=false).")
        alto = True
        motivos.append("es un DELETE (borrado)")

    if metodo in ("PUT", "DELETE", "PATCH") and not resource_id:
        alto = True
        motivos.append("sin id: puede afectar multiples registros")

    api_lower = (api_id or "").lower()
    for pat in high_risk_patterns:
        if pat.lower() in api_lower:
            alto = True
            motivos.append(f"endpoint sensible (coincide con '{pat}')")
            break

    motivo = "; ".join(motivos) if motivos else "operacion estandar"
    return (False, alto, motivo)
