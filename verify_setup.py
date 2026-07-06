"""Verificacion de instalacion del Agente Finnegans.

Ejecutar desde la carpeta del proyecto despues de configurar .env:

    python verify_setup.py

Devuelve codigo de salida 0 si todo OK, 1 si hay errores.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLACEHOLDERS = ("tu_client_id", "tu_client_secret", "tu_docs_client_id", "tu_docs_secret_key")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [ERROR] {msg}")


def warn(msg: str) -> None:
    print(f"  [AVISO] {msg}")


def check_python() -> bool:
    print("\n1. Python")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        fail(f"Se requiere Python 3.10+. Encontrado: {sys.version}")
        return False
    ok(f"Python {v.major}.{v.minor}.{v.micro}")
    ok(f"Ejecutable: {sys.executable}")
    return True


def check_env_file() -> bool:
    print("\n2. Archivo .env")
    env_path = ROOT / ".env"
    if not env_path.exists():
        fail("No existe .env. Ejecuta: copy .env.example .env")
        return False
    ok(f"Encontrado: {env_path}")

    content = env_path.read_text(encoding="utf-8")
    errors = False
    required = [
        "FINNEGANS_CLIENT_ID",
        "FINNEGANS_CLIENT_SECRET",
        "FINNEGANS_DOCS_CLIENT_ID",
        "FINNEGANS_DOCS_SECRET_KEY",
    ]
    for key in required:
        if key not in content:
            fail(f"Falta la variable {key} en .env")
            errors = True
            continue
        for line in content.splitlines():
            if line.startswith(f"{key}="):
                val = line.split("=", 1)[1].strip()
                if not val:
                    fail(f"{key} esta vacio")
                    errors = True
                elif val in PLACEHOLDERS:
                    fail(f"{key} sigue con valor de ejemplo ({val})")
                    errors = True
                else:
                    ok(f"{key} configurado (len={len(val)})")
                break
    return not errors


def check_dependencies() -> bool:
    print("\n3. Dependencias Python")
    try:
        import mcp  # noqa: F401
        ok("Paquete 'mcp' instalado")
        return True
    except ImportError:
        fail("Falta el paquete 'mcp'. Ejecuta: python -m pip install -r requirements.txt")
        return False


def check_api_connection() -> bool:
    print("\n4. Conexion API Finnegans (ejecucion)")
    try:
        from finnegans import FinnegansClient, FinnegansError

        client = FinnegansClient(timeout=20)
        token = client.get_token(force_refresh=True)
        ok(f"Token obtenido (longitud {len(token)})")
        return True
    except Exception as e:  # noqa: BLE001
        fail(f"No se pudo autenticar: {e}")
        warn("Revisa FINNEGANS_CLIENT_ID y FINNEGANS_CLIENT_SECRET en .env")
        return False


def check_docs_catalog() -> bool:
    print("\n5. Catalogo de APIs (documentacion)")
    try:
        from finnegans.discovery import search_apis

        result = search_apis("producto")
        if isinstance(result, dict) and result.get("count", 0) > 0:
            ok(f"Busqueda de prueba OK ({result['count']} APIs encontradas)")
            return True
        fail(f"Respuesta inesperada: {result}")
        return False
    except Exception as e:  # noqa: BLE001
        fail(f"No se pudo consultar el catalogo: {e}")
        warn("Revisa FINNEGANS_DOCS_CLIENT_ID y FINNEGANS_DOCS_SECRET_KEY en .env")
        return False


def check_mcp_server() -> bool:
    print("\n6. Servidor MCP (server.py)")
    try:
        import asyncio
        import server

        tools = asyncio.run(server.mcp.list_tools())
        names = [t.name for t in tools]
        expected = {
            "verificar_conexion",
            "buscar_api",
            "ver_api",
            "consultar_finnegans",
            "preparar_cambio",
            "ejecutar_cambio",
        }
        if expected.issubset(set(names)):
            ok(f"Tools registradas: {', '.join(names)}")
            return True
        fail(f"Faltan tools. Encontradas: {names}")
        return False
    except Exception as e:  # noqa: BLE001
        fail(f"Error importando server.py: {e}")
        return False


def _claude_config_paths() -> tuple[Path | None, Path | None]:
    """Return (msix_config, legacy_config) if they exist."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    legacy = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    msix: Path | None = None
    packages = local / "Packages"
    if packages.is_dir():
        for pkg_dir in sorted(packages.glob("Claude_*")):
            candidate = (
                pkg_dir / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
            )
            if candidate.exists():
                msix = candidate
                break
    return msix, legacy if legacy.exists() else None


def check_claude_config_hint() -> None:
    print("\n7. Claude Desktop (verificacion manual)")
    msix_config, legacy_config = _claude_config_paths()
    config = msix_config or legacy_config

    if msix_config:
        ok(f"Config MSIX encontrado: {msix_config}")
        if legacy_config:
            warn(f"Tambien existe config clasico (puede ser el que abre Edit Config): {legacy_config}")
            warn("En MSIX, Claude lee el de Packages. Edita ese (ver README Paso 6.2).")
    elif legacy_config:
        ok(f"Config clasico encontrado: {legacy_config}")
    else:
        warn("No se encontro claude_desktop_config.json")
        warn("Crealo al configurar Claude Desktop (ver README Paso 6.2).")

    if config and config.exists():
        content = config.read_text(encoding="utf-8")
        if "finnegans-agent" in content:
            ok("Entrada 'finnegans-agent' presente en claude_desktop_config.json")
        else:
            warn("No se encontro 'finnegans-agent' en claude_desktop_config.json")
            print("       Agrega la entrada MCP (ver README seccion Instalacion IT).")

    print("\n  Bloque JSON sugerido para claude_desktop_config.json:")
    suggested = {
        "mcpServers": {
            "finnegans-agent": {
                "type": "stdio",
                "command": sys.executable,
                "args": [str((ROOT / "server.py").resolve())],
                "cwd": str(ROOT.resolve()),
            }
        }
    }
    print(json.dumps(suggested, indent=2, ensure_ascii=False))


def main() -> int:
    print("=" * 60)
    print("VERIFICACION DE INSTALACION — Agente Finnegans")
    print("=" * 60)

    results = [
        check_python(),
        check_env_file(),
        check_dependencies(),
        check_api_connection(),
        check_docs_catalog(),
        check_mcp_server(),
    ]
    check_claude_config_hint()

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"RESULTADO: TODO OK ({passed}/{total} checks automaticos)")
        print("Siguiente paso: reiniciar Claude Desktop y probar en el chat.")
        return 0
    print(f"RESULTADO: HAY ERRORES ({passed}/{total} checks OK)")
    print("Corregi los puntos marcados [ERROR] antes de entregar la PC al lider.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
