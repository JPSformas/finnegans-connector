"""Log de auditoria append-only (JSONL) para el conector Finnegans.

Registra cada preparacion/ejecucion/rechazo con identidad de operador.
Nunca escribe tokens ni secretos.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSIBLE = ("access_token", "token", "secret", "password", "client_secret")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in _SENSIBLE):
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


class AuditLog:
    """Escribe eventos de auditoria, uno por linea (JSONL)."""

    def __init__(self, path: str, operator: str) -> None:
        self.path = Path(path)
        self.operator = operator or "(sin operador)"

    def record(
        self,
        evento: str,
        *,
        metodo: str = "",
        api_id: str = "",
        resource_id: str | None = None,
        parametros: dict | None = None,
        body: Any = None,
        confirmacion_id: str = "",
        codigo_ok: bool | None = None,
        resultado: str = "",
        detalle: Any = None,
    ) -> None:
        rec = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "operador": self.operator,
            "evento": evento,
            "metodo": metodo,
            "api_id": api_id,
            "resource_id": resource_id,
            "parametros": _redact(parametros or {}),
            "body": _redact(body),
            "confirmacion_id": confirmacion_id,
            "codigo_ok": codigo_ok,
            "resultado": resultado,
            "detalle": _redact(detalle),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
