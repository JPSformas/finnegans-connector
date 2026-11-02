"""El manifest MCPB y la configuracion del servidor tienen que decir lo mismo."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from finnegans_core.config import Settings
from finnegans_mcp.server import crear_servidor

RAIZ = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((RAIZ / "manifest.json").read_text(encoding="utf-8"))
SENSIBLES = {"client_secret", "swagger_key", "docs_secret_key"}


def _variables_de_settings() -> set[str]:
    """Nombres de variable que lee Settings.from_env, tomados del propio codigo."""
    fuente = (RAIZ / "src" / "finnegans_core" / "config.py").read_text(encoding="utf-8")
    return set(re.findall(r'"(FINNEGANS_[A-Z_]+)"', fuente))


def test_manifest_y_settings_coinciden():
    env = MANIFEST["server"]["mcp_config"]["env"]
    config = MANIFEST["user_config"]

    # Cada variable apunta a una clave que existe en el formulario.
    for variable, valor in env.items():
        m = re.fullmatch(r"\$\{user_config\.([a-z_]+)\}", valor)
        assert m, f"{variable}: {valor}"
        assert m.group(1) in config, f"{variable} apunta a una clave inexistente"
    # Y cada clave del formulario llega al servidor.
    usadas = {re.fullmatch(r"\$\{user_config\.([a-z_]+)\}", v).group(1) for v in env.values()}
    assert usadas == set(config)

    # Toda variable que lee Settings.from_env esta en el manifest.
    leidas = _variables_de_settings()
    assert len(leidas) == 9
    assert leidas == set(env)

    # Solo las tres claves secretas se enmascaran.
    assert {k for k, v in config.items() if v.get("sensitive")} == SENSIBLES

    # Las cinco credenciales son obligatorias; lo demas tiene valor por defecto.
    obligatorias = {k for k, v in config.items() if v.get("required")}
    assert obligatorias == {
        "client_id", "client_secret", "swagger_key", "docs_client_id", "docs_secret_key",
    }
    for clave in set(config) - obligatorias:
        assert config[clave].get("default"), clave
    assert config["carpeta_exportacion"]["type"] == "directory"
    assert config["carpeta_exportacion"]["default"] == "${DOCUMENTS}/Finnegans"


def test_manifest_arranca_con_uv_y_python_312():
    server = MANIFEST["server"]
    assert MANIFEST["manifest_version"] == "0.4"
    assert server["type"] == "uv"
    assert server["entry_point"] == "src/finnegans_mcp/server.py"
    assert server["mcp_config"]["command"] == "uv"
    assert server["mcp_config"]["args"] == [
        "run", "--directory", "${__dirname}", "src/finnegans_mcp/server.py",
    ]
    assert (RAIZ / server["entry_point"]).is_file()
    assert MANIFEST["compatibility"]["platforms"] == ["win32"]
    assert MANIFEST["compatibility"]["runtimes"]["python"] == ">=3.12"
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12"' in pyproject


def test_tools_del_manifest_son_las_del_servidor():
    registradas = {t.name for t in asyncio.run(crear_servidor(Settings()).list_tools())}
    declaradas = [t["name"] for t in MANIFEST["tools"]]
    assert len(declaradas) == len(set(declaradas))
    assert set(declaradas) == registradas
    assert all(t["description"].strip() for t in MANIFEST["tools"])


def test_manifest_no_lleva_valores_de_claves():
    texto = (RAIZ / "manifest.json").read_text(encoding="utf-8")
    assert not re.search(r"(?i)bearer|secret\s*[:=]\s*\S{12,}", texto)


def test_version_igual_en_manifest_pyproject_y_servidor():
    import tomllib

    from mcp.client import Client

    from finnegans_mcp import __version__

    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert MANIFEST["version"] == pyproject["project"]["version"] == __version__ == "1.0.1"

    async def _server_info():
        async with Client(crear_servidor(Settings())) as cliente:
            return cliente.server_info

    info = asyncio.run(_server_info())
    assert info.name == "finnegans"
    assert info.version == __version__
