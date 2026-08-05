"""Instalador del conector Finnegans para una PC (opcion B).

Uso (IT, en la PC del usuario):
    python install.py

Pide el nombre del operador, escribe .env a partir de service-credentials.env,
registra el server en claude_desktop_config.json y corre verify_setup.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render_env(template: str, operator: str) -> str:
    """Devuelve el contenido de .env con el operador insertado."""
    lineas = []
    visto = False
    for line in template.splitlines():
        if line.startswith("FINNEGANS_OPERATOR="):
            lineas.append(f"FINNEGANS_OPERATOR={operator}")
            visto = True
        else:
            lineas.append(line)
    if not visto:
        lineas.append(f"FINNEGANS_OPERATOR={operator}")
    return "\n".join(lineas) + "\n"


def upsert_mcp_entry(config: dict, python_exe: str, script: str, cwd: str) -> dict:
    """Inserta/actualiza la entrada 'finnegans-agent' en el config de Claude."""
    config = dict(config)
    servers = dict(config.get("mcpServers", {}))
    servers["finnegans-agent"] = {"command": python_exe, "args": [script], "cwd": cwd}
    config["mcpServers"] = servers
    return config


def main() -> int:
    cred = ROOT / "service-credentials.env"
    if not cred.exists():
        print("[ERROR] Falta service-credentials.env (copiar de .example y completar).")
        return 1

    operator = input("Nombre y email del operador (ej. Juan <j@x.com>): ").strip()
    if not operator:
        print("[ERROR] El operador es obligatorio para la auditoria.")
        return 1

    (ROOT / ".env").write_text(
        render_env(cred.read_text(encoding="utf-8"), operator), encoding="utf-8"
    )
    print("[OK] .env escrito.")

    from verify_setup import _primary_claude_desktop_config

    cfg_path = _primary_claude_desktop_config()
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
    cfg = upsert_mcp_entry(cfg, sys.executable, str(ROOT / "server.py"), str(ROOT))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Registrado en {cfg_path}")

    print("\nVerificando instalacion...")
    import verify_setup
    return verify_setup.main()


if __name__ == "__main__":
    sys.exit(main())
