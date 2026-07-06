"""CLI simple para consultar la API de Finnegans.

Ejemplos:
    python cli.py token
    python cli.py get producto --id ABC123
    python cli.py get ACOrdenesCompraPendientes --id 000123
    python cli.py get cliente --id 100 --param origen=web

Convencion de la API: GET /api/{recurso}/{id}?ACCESS_TOKEN=...
El id va en el PATH. Los reportes/listados pueden requerir parametros
adicionales definidos en el Diccionario de APIs del espacio de trabajo.
"""
from __future__ import annotations

import argparse
import json
import sys

from finnegans import FinnegansClient, FinnegansError


def parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"Parametro invalido '{pair}'. Usar clave=valor.")
        k, _, v = pair.partition("=")
        params[k.strip()] = v.strip()
    return params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas a la API de Finnegans")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("token", help="Obtener y mostrar (enmascarado) un token")

    g = sub.add_parser("get", help="GET a un recurso")
    g.add_argument("endpoint", help="Nombre del recurso, ej. producto")
    g.add_argument("--id", default=None, help="Codigo/id (va en el path)")
    g.add_argument("--param", action="append", default=[], help="Filtro clave=valor (repetible)")
    g.add_argument("--timeout", type=int, default=20)

    args = parser.parse_args(argv)

    try:
        client = FinnegansClient(timeout=getattr(args, "timeout", 20))
        if args.cmd == "token":
            t = client.get_token()
            masked = t[:6] + "..." + t[-4:] if len(t) > 12 else "***"
            print(f"Token OK (len={len(t)}): {masked}")
            return 0
        if args.cmd == "get":
            data = client.get(args.endpoint, id=args.id, params=parse_params(args.param) or None)
            if isinstance(data, (dict, list)):
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print(data)
            return 0
    except FinnegansError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
