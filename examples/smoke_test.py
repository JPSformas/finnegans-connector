"""Smoke test: valida auth y explora el comportamiento real de la API.

Prueba varios endpoints de lectura y muestra un resumen de lo que
devuelven (tipo, cantidad, primeras claves) sin volcar datos sensibles
completos ni el token.

Uso:
    python -m examples.smoke_test
"""
from __future__ import annotations

import sys

from finnegans import FinnegansClient, FinnegansError


def describe(name: str, value) -> None:
    print(f"\n=== {name} ===")
    if isinstance(value, list):
        print(f"tipo: lista  cantidad: {len(value)}")
        if value:
            first = value[0]
            if isinstance(first, dict):
                print("claves[0]:", list(first.keys())[:15])
            else:
                print("primer item:", str(first)[:200])
    elif isinstance(value, dict):
        print("tipo: dict  claves:", list(value.keys())[:20])
    else:
        print("tipo:", type(value).__name__, " preview:", str(value)[:300])


def try_call(client: FinnegansClient, name: str, fn) -> None:
    try:
        describe(name, fn())
    except FinnegansError as e:
        print(f"\n=== {name} ===")
        print("ERROR:", str(e)[:300])


def main() -> int:
    client = FinnegansClient(timeout=20)
    print("Autenticando...")
    token = client.get_token()
    print(f"Token OK (len={len(token)}).")

    # Convencion confirmada: GET /api/{recurso}/{id}. Con un id inexistente
    # se obtiene 404 (peticion bien formada). Reemplazar por codigos reales
    # del maestro para obtener 200 + datos.
    try_call(client, "producto (codigo demo)", lambda: client.producto("CODIGO_DEMO"))
    try_call(client, "cliente (codigo demo)", lambda: client.cliente("CODIGO_DEMO"))

    print("\nNota: para ver datos reales (200), usa codigos existentes de tu maestro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
