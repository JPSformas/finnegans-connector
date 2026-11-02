"""Fakes compartidos por los tests del servidor MCP.

Todas las claves son falsas. El swagger es el catalogo real servido por un
transporte falso; el cliente de Finnegans y el MCP de docs son fakes.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

import httpx2
import pytest

from finnegans_core.catalogo.swagger import SwaggerCatalog
from finnegans_core.client import FinnegansError
from finnegans_core.config import Settings
from finnegans_core.secretos import Redactor
from finnegans_core.workspace import Workspace
from finnegans_mcp.server import crear_servidor

CLIENT_ID = "cid-falso-1a2b3c"
CLIENT_SECRET = "secreto-falso-4d5e6f"
SWAGGER_KEY = "swkey-falsa-7g8h9i"
DOCS_ID = "docsid-falso-0j1k"
DOCS_KEY = "docskey-falsa-2l3m"
SWAGGER_URL = "https://oneteam.finneg.com/BSA/api/swaggerGlobal"

REF_CLIENTE = "/BSA/api/swaggerApi?key=abc123&api=cliente&nombreVO=ClienteVO"

VO_CLIENTE = {
    "required": ["Codigo", "Nombre"],
    "properties": {
        "Codigo": {"type": "string"},
        "Nombre": {"type": "string"},
        "Descripcion": {"type": "string"},
        "NroInscripcionIIBB": {"type": "string"},
        "ProvinciaItems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ControlImpositivo1": {"type": "string",
                                           "description": "Situacion de IIBB"},
                    "Provincia": {"type": "string"},
                },
            },
        },
    },
}


def _op(tags, summary="", opid="", params=None):
    d = {"tags": tags, "summary": summary, "operationId": opid}
    if params is not None:
        d["parameters"] = params
    return d


SPEC = {
    "swagger": "2.0",
    "basePath": "/api",
    "tags": [
        {"name": "cliente", "description": "Entidad cliente. Tipo: EntidadVO"},
        {"name": "ACOrdenesCompraPendientes", "description": "Reporte. Tipo: Viewer"},
    ],
    "definitions": {
        "ParametroToken": {"name": "ACCESS_TOKEN", "in": "query", "required": True},
        "ParametroCodigo": {"name": "codigo", "in": "path", "required": True,
                            "description": "Codigo de la entidad"},
        "ParametroForceInsert": {"name": "createIfNotExists", "in": "query",
                                 "required": False, "description": "Crear si no existe"},
    },
    "paths": {
        "/cliente": {
            "post": _op(["cliente"], "Alta de cliente", "cliente_post",
                        [{"name": "ClienteVO", "in": "body", "required": True,
                          "schema": {"$ref": REF_CLIENTE}}]),
        },
        "/cliente/list": {"get": _op(["cliente"], "Lista de clientes", "cliente_list", [])},
        "/cliente/{codigo}": {
            "get": _op(["cliente"], "Cliente", "cliente_get", []),
            "put": _op(["cliente"], "Modifica cliente", "cliente_put",
                       [{"name": "ClienteVO", "in": "body", "required": True,
                         "schema": {"$ref": REF_CLIENTE}},
                        {"$ref": "#/definitions/ParametroForceInsert"}]),
            "delete": _op(["cliente"], "Baja de cliente", "cliente_delete", []),
            "parameters": [{"$ref": "#/definitions/ParametroToken"},
                           {"$ref": "#/definitions/ParametroCodigo"}],
        },
        "/reports/ACOrdenesCompraPendientes": {"get": _op(
            ["ACOrdenesCompraPendientes"], "Ordenes de compra pendientes",
            "reports_ACOrdenesCompraPendientes",
            [{"name": "PARAM_Fechadesde", "in": "query", "required": False,
              "description": "Fecha desde"}])},
    },
}

VOS = {"ClienteVO": VO_CLIENTE}


def spec_grande(n: int = 600) -> dict:
    """Spec con n viewers bajo /reports, todos con resumenes y parametros largos."""
    spec = copy.deepcopy(SPEC)
    for i in range(n):
        nombre = f"ReporteClientes{i:04d}"
        spec["tags"].append({"name": nombre, "description": "Reporte. Tipo: Viewer"})
        spec["paths"][f"/reports/{nombre}"] = {"get": _op(
            [nombre], f"Reporte de clientes numero {i} " + "x" * 150, f"reports_{nombre}",
            [{"name": f"PARAM_Filtro{j}", "in": "query", "required": j == 0,
              "description": "descripcion larga " * 5} for j in range(6)])}
    return spec


def ajustes(tmp_path, **cambios) -> Settings:
    base = dict(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        swagger_key=SWAGGER_KEY,
        docs_client_id=DOCS_ID,
        docs_secret_key=DOCS_KEY,
        export_dir=str(tmp_path / "export"),
        swagger_url=SWAGGER_URL,
    )
    base.update(cambios)
    return Settings(**base)


def catalogo(settings: Settings, spec: dict, vos: dict | None = None,
             status: int = 200) -> SwaggerCatalog:
    vos = VOS if vos is None else vos

    def red(req: httpx2.Request) -> httpx2.Response:
        if req.url.path.endswith("swaggerGlobal"):
            if status != 200:
                return httpx2.Response(status, text="clave invalida")
            return httpx2.Response(200, json=spec)
        vo = vos.get(req.url.params.get("nombreVO"))
        if vo is None:
            return httpx2.Response(404, text="no existe")
        return httpx2.Response(200, json=vo)

    return SwaggerCatalog(settings, http=httpx2.Client(transport=httpx2.MockTransport(red)))


@dataclass
class Llamada:
    metodo: str
    path: str
    id: str | None
    params: dict | None
    body: Any


class ClienteFalso:
    """Imita FinnegansClient: registra cada llamada y responde con `handler`."""

    def __init__(self, settings: Settings,
                 handler: Callable[..., Any] | None = None,
                 error_token: Exception | None = None) -> None:
        self.settings = settings
        self.redactor = Redactor(settings.secretos())
        self.handler = handler or (lambda metodo, path, id, params, body: {})
        self.error_token = error_token
        self.llamadas: list[Llamada] = []

    def request(self, metodo, path, id=None, params=None, body=None):
        self.llamadas.append(Llamada(metodo, path, id, copy.deepcopy(params),
                                     copy.deepcopy(body)))
        return self.handler(metodo, path, id, params, body)

    def token(self, forzar: bool = False) -> str:
        if self.error_token is not None:
            raise self.error_token
        return "token-falso"


class DocsFalso:
    def __init__(self, filas=None, error: Exception | None = None) -> None:
        self.filas = filas or []
        self.error = error
        self.consultas: list[str] = []

    async def buscar(self, consulta: str) -> list[dict]:
        self.consultas.append(consulta)
        if self.error is not None:
            raise self.error
        return list(self.filas)


@dataclass
class Entorno:
    server: Any
    cliente: ClienteFalso
    workspace: Workspace
    settings: Settings
    docs: Any

    async def llamar(self, _herramienta: str, **argumentos) -> str:
        r = await self.server.call_tool(_herramienta, argumentos)
        assert not r.is_error, r
        return "".join(c.text for c in r.content)


@pytest.fixture
def armar(tmp_path):
    abiertos: list[Workspace] = []

    def _armar(handler=None, spec=SPEC, vos=None, docs=None, settings=None,
               error_token=None, status_swagger=200, usar_docs_real=False) -> Entorno:
        s = settings or ajustes(tmp_path)
        cli = ClienteFalso(s, handler, error_token=error_token)
        sw = catalogo(s, spec, vos, status=status_swagger)
        ws = Workspace()
        abiertos.append(ws)
        d = None if usar_docs_real else (docs or DocsFalso())
        server = crear_servidor(s, client=cli, swagger=sw, docs=d, workspace=ws)
        return Entorno(server, cli, ws, s, d)

    yield _armar
    for ws in abiertos:
        ws.cerrar()


def error_con_secreto(settings: Settings) -> FinnegansError:
    return FinnegansError(
        f"Error en PUT cliente (HTTP 500): fallo con client_secret={settings.client_secret} "
        f"y client_id={settings.client_id}"
    )
