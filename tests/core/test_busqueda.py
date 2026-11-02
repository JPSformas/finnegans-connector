"""Busqueda unificada: swagger + MCP de documentacion."""
import json
from pathlib import Path

import pytest

from finnegans_core.catalogo.busqueda import (
    FilaBusqueda,
    ResultadoBusqueda,
    buscar_endpoint,
    formatear_busqueda,
)
from finnegans_core.catalogo.docs_mcp import DocsMcp, DocsMcpError
from finnegans_core.catalogo.swagger import Coincidencia
from finnegans_core.config import Settings

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).parent.parent / "fixtures" / "docs_search_apis.json"
DOCS_ID = "id-docs-secreto-123"
DOCS_KEY = "key/docs+secreta=456"


def _coin(path, puntaje=2.0, cobertura=1.0, tipo="viewer", metodos=("GET",), resumen=""):
    return Coincidencia(path=path, metodos=list(metodos), tipo=tipo,
                        resumen=resumen, puntaje=puntaje, cobertura=cobertura)


class SwaggerFalso:
    def __init__(self, coincidencias, tipos=None):
        self._coincidencias = coincidencias
        self._tipos = tipos or {}

    def buscar(self, consulta, limite=8):
        return self._coincidencias[:limite]

    def tipo(self, path):
        return self._tipos.get(path, "otro")

    def spec(self):
        return {"paths": {c.path: {m.lower(): {} for m in c.metodos}
                          for c in self._coincidencias}}


class DocsFalso:
    def __init__(self, filas=None, error=None):
        self.filas = filas or []
        self.error = error

    async def buscar(self, consulta):
        if self.error:
            raise self.error
        return self.filas


async def test_une_por_path_y_marca_fuentes():
    sw = SwaggerFalso([_coin("/reports/A", 3.0, resumen="Orden A"),
                       _coin("/reports/B", 2.0)])
    docs = DocsFalso([{"path": "A", "resumen": "desc docs"}])
    r = await buscar_endpoint("ordenes", sw, docs)
    assert [f.path for f in r.filas] == ["/reports/A", "/reports/B"]
    assert r.filas[0].fuentes == ["swagger", "docs"]
    assert r.filas[1].fuentes == ["swagger"]
    assert r.notas == []


async def test_docs_solo_se_agrega_al_final_con_tipo_del_swagger():
    sw = SwaggerFalso([_coin("/reports/A", 3.0), _coin("/reports/B", 2.0)],
                      tipos={"/otro/X": "entidad"})
    docs = DocsFalso([{"path": "/otro/X", "resumen": "solo docs"}])
    r = await buscar_endpoint("x", sw, docs)
    assert [f.path for f in r.filas] == ["/reports/A", "/reports/B", "/otro/X"]
    ultima = r.filas[-1]
    assert ultima.fuentes == ["docs"]
    assert ultima.tipo == "entidad"
    assert ultima.resumen == "solo docs"


async def test_nota_si_las_fuentes_no_coinciden():
    sw = SwaggerFalso([_coin("/reports/A", 3.0), _coin("/reports/B", 2.0)])
    docs = DocsFalso([{"path": "Z", "resumen": ""}, {"path": "A", "resumen": ""}])
    r = await buscar_endpoint("x", sw, docs)
    assert any("las fuentes no coinciden" in n for n in r.notas)


async def test_nota_si_hay_empate():
    sw = SwaggerFalso([_coin("/reports/A", 2.5), _coin("/reports/B", 2.5)])
    r = await buscar_endpoint("x", sw, DocsFalso([{"path": "A", "resumen": ""}]))
    assert any("empate" in n for n in r.notas)


async def test_nota_si_coincidencia_parcial():
    sw = SwaggerFalso([_coin("/reports/A", 3.0, cobertura=0.5),
                       _coin("/reports/B", 2.0, cobertura=0.5)])
    r = await buscar_endpoint("x", sw, DocsFalso([{"path": "A", "resumen": ""}]))
    assert any("coincidencia parcial" in n for n in r.notas)


async def test_sin_notas_si_todo_coincide_bien():
    sw = SwaggerFalso([_coin("/reports/A", 3.0), _coin("/reports/B", 2.0)])
    r = await buscar_endpoint("x", sw, DocsFalso([{"path": "A", "resumen": ""}]))
    assert r.notas == []


async def test_toda_nota_termina_pidiendo_al_usuario():
    sw = SwaggerFalso([_coin("/reports/A", 2.5, cobertura=0.5),
                       _coin("/reports/B", 2.5, cobertura=0.5)])
    r = await buscar_endpoint("x", sw, DocsFalso([{"path": "Z", "resumen": ""}]))
    assert len(r.notas) == 3
    assert all(n.endswith("preguntale al usuario") for n in r.notas)


@pytest.mark.parametrize("docs", [
    DocsFalso(error=DocsMcpError("sin red")),
    DocsFalso(error=RuntimeError("explotó")),
    None,
])
async def test_sigue_solo_con_swagger_si_docs_falla(docs):
    sw = SwaggerFalso([_coin("/reports/A", 3.0), _coin("/reports/B", 2.0)])
    r = await buscar_endpoint("x", sw, docs)
    assert [f.path for f in r.filas] == ["/reports/A", "/reports/B"]
    assert all(f.fuentes == ["swagger"] for f in r.filas)
    nota = next(n for n in r.notas if "solo con el swagger" in n)
    assert nota.endswith("preguntale al usuario")
    assert not any("las fuentes no coinciden" in n for n in r.notas)


async def test_sin_resultados_en_ninguna_fuente():
    r = await buscar_endpoint("x", SwaggerFalso([]), DocsFalso([]))
    assert r.filas == []
    assert "No encontré" in formatear_busqueda(r)


def test_formatear_una_linea_por_fila_y_notas():
    r = ResultadoBusqueda(
        filas=[
            FilaBusqueda("/reports/X", ["GET"], "viewer", "Un resumen", ["swagger", "docs"]),
            FilaBusqueda("/ordenCompra", ["GET", "POST"], "entidad", "", ["swagger"]),
        ],
        notas=["hay un empate; preguntale al usuario"],
    )
    lineas = formatear_busqueda(r).splitlines()
    assert lineas[0] == "- GET /reports/X [viewer] Un resumen (swagger+docs)"
    assert lineas[1] == "- GET,POST /ordenCompra [entidad] (swagger)"
    assert "Notas:" in lineas
    assert lineas[-1] == "- hay un empate; preguntale al usuario"


# ------------------------------------------------------------------ DocsMcp

def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parsea_respuesta_real_de_docs():
    filas = DocsMcp.parsear(_fixture())
    assert filas
    assert all(f["path"] for f in filas)
    assert "ACOrdenesCompraDetalle" in [f["path"] for f in filas]
    assert all(set(f) == {"path", "resumen"} for f in filas)


def test_parsea_desde_el_texto_si_no_hay_contenido_estructurado():
    crudo = _fixture()
    crudo.pop("structuredContent")
    assert DocsMcp.parsear(crudo) == DocsMcp.parsear(_fixture())


def test_parsea_sin_resultados():
    assert DocsMcp.parsear({"content": [{"type": "text", "text":
        json.dumps({"status": "not_found", "results": []})}]}) == []


def test_parsea_error_de_la_herramienta():
    with pytest.raises(DocsMcpError):
        DocsMcp.parsear({"isError": True, "content": [{"type": "text", "text": "boom"}]})


def _settings(**extra):
    env = {"FINNEGANS_DOCS_CLIENT_ID": DOCS_ID, "FINNEGANS_DOCS_SECRET_KEY": DOCS_KEY}
    env.update(extra)
    return Settings.from_env(env)


async def test_sin_credenciales_falla_rapido_sin_red():
    docs = DocsMcp(Settings.from_env({}))
    with pytest.raises(DocsMcpError, match="credenciales"):
        await docs.buscar("ordenes")


async def test_errores_de_docs_salen_redactados(monkeypatch):
    docs = DocsMcp(_settings())

    async def _roto(consulta):
        raise RuntimeError(f"fallo en https://x?id={DOCS_ID}&k={DOCS_KEY}")

    monkeypatch.setattr(docs, "_llamar", _roto)
    with pytest.raises(DocsMcpError) as exc:
        await docs.buscar("ordenes")
    msg = str(exc.value)
    assert DOCS_ID not in msg and DOCS_KEY not in msg
    assert "***" in msg


async def test_buscar_devuelve_filas_parseadas(monkeypatch):
    docs = DocsMcp(_settings())

    async def _ok(consulta):
        return _fixture()

    monkeypatch.setattr(docs, "_llamar", _ok)
    assert len(await docs.buscar("ordenes de compra")) == 6
