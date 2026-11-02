"""Tools del servidor MCP, llamadas a traves del registro del servidor."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from finnegans_core.catalogo.docs_mcp import DocsMcpError
from finnegans_core.client import FinnegansAuthError
from finnegans_core.guia import TEMAS
from finnegans_core.presupuesto import RESPUESTA_MAX_CHARS

from .conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    DOCS_KEY,
    SWAGGER_KEY,
    DocsFalso,
    ajustes,
    error_con_secreto,
    spec_grande,
)

pytestmark = pytest.mark.anyio

HERRAMIENTAS = {
    "buscar_endpoint", "ver_endpoint", "leer", "consultar", "exportar",
    "escribir", "guia", "verificar_conexion",
}


def _cliente(codigo: str, **extra) -> dict:
    d = {
        "Codigo": codigo,
        "Nombre": f"Cliente {codigo}",
        "Descripcion": "descripcion " * 3,
        "ProvinciaItems": [{"Provincia": "BA", "ControlImpositivo1": "LOCAL"}],
    }
    d.update(extra)
    return d


CLIENTES = [_cliente(f"P{i:05d}") for i in range(4150)]


def _secciones(out: str) -> tuple[str, str]:
    marca = "Campos que la API cambió por su cuenta"
    assert marca in out
    antes, despues = out.split(marca, 1)
    return antes, despues


# ------------------------------------------------------------- registro


async def test_registro_tiene_las_ocho_tools(armar):
    env = armar()
    nombres = {t.name for t in await env.server.list_tools()}
    assert nombres == HERRAMIENTAS


async def test_todas_las_tools_tienen_anotaciones(armar):
    env = armar()
    for t in await env.server.list_tools():
        assert t.annotations is not None, t.name
        assert t.description, t.name


async def test_reads_y_writes_son_tools_distintas(armar):
    env = armar()
    tools = {t.name: t for t in await env.server.list_tools()}
    assert "leer" in tools and "escribir" in tools
    assert tools["leer"].annotations.read_only_hint is True
    assert tools["escribir"].annotations.destructive_hint is True
    assert tools["escribir"].annotations.read_only_hint is not True
    assert "metodo" not in tools["leer"].input_schema["properties"]
    assert "params" in tools["escribir"].input_schema["properties"]


# ------------------------------------------------------------- presupuesto


async def test_ninguna_respuesta_supera_el_presupuesto(armar, tmp_path):
    ancho = {f"Campo{j:03d}": "v" * 40 for j in range(500)}
    anidado = {f"sub{j:03d}": {"a": j, "b": "texto"} for j in range(300)}
    anchos = [dict(_cliente(f"A{i:04d}"), **ancho, Anidado=anidado) for i in range(50)]
    base_ancha = dict(_cliente("P00001"), **{f"Campo{j:03d}": "viejo" for j in range(600)})
    releido = dict(_cliente("P00001"), **{f"Campo{j:03d}": "nuevo" * 30 for j in range(600)})

    def handler(metodo, path, id, params, body):
        if metodo == "GET" and path == "cliente/list":
            return CLIENTES
        if metodo == "GET" and path == "anchos":
            return anchos
        if metodo == "GET" and path == "cliente" and id == "P00001":
            ya_escrito = any(c.metodo == "PUT" for c in env.cliente.llamadas)
            return releido if ya_escrito else base_ancha
        if metodo == "GET" and path == "texto":
            return "z" * 50000
        return {"ok": True}

    docs = DocsFalso([{"path": f"ReporteClientes{i:04d}", "resumen": "r" * 300}
                      for i in range(600)])
    vo_enorme = copy.deepcopy(
        {"ClienteVO": {"required": ["Codigo", "Campo599"], "properties": {
            "Codigo": {"type": "string"},
            "Items": {"type": "array", "items": {"type": "object", "properties": {
                f"Sub{j:03d}": {"type": "string", "description": "d" * 100}
                for j in range(400)}}},
            **{f"Campo{j:03d}": {"type": "string"} for j in range(600)},
        }}})
    env = armar(handler, spec=spec_grande(600), docs=docs, vos=vo_enorme)

    salidas = {}
    salidas["buscar"] = await env.llamar("buscar_endpoint", consulta="reporte clientes")
    salidas["ver_reports"] = await env.llamar("ver_endpoint", path="reports")
    salidas["ver_cliente"] = await env.llamar("ver_endpoint", path="cliente")
    salidas["ver_campo"] = await env.llamar("ver_endpoint", path="cliente", campo="Items")
    salidas["leer"] = await env.llamar("leer", path="cliente/list")
    salidas["leer_anchos"] = await env.llamar("leer", path="anchos")
    salidas["leer_texto"] = await env.llamar("leer", path="texto")
    salidas["consultar"] = await env.llamar("consultar", sql="SELECT * FROM cliente")
    salidas["consultar_anchos"] = await env.llamar("consultar", sql="SELECT * FROM anchos")
    salidas["exportar"] = await env.llamar("exportar", sql="SELECT * FROM cliente",
                                           formato="csv")
    await env.llamar("leer", path="cliente", id="P00001", tabla="base_ancha")
    salidas["escribir"] = await env.llamar(
        "escribir", metodo="PUT", path="cliente", id="P00001", base="base_ancha",
        cambios={f"Campo{j:03d}": "nuevo" * 30 for j in range(600)})
    salidas["guia"] = await env.llamar("guia")
    for tema in TEMAS:
        salidas[f"guia_{tema}"] = await env.llamar("guia", tema=tema)
    salidas["verificar"] = await env.llamar("verificar_conexion")

    for nombre, out in salidas.items():
        assert len(out) <= RESPUESTA_MAX_CHARS, (nombre, len(out))
    # Achicar no esconde lo importante: los requeridos del VO enorme se ven.
    assert "Codigo*" in salidas["ver_cliente"] and "Campo599*" in salidas["ver_cliente"]
    assert "campos más" in salidas["ver_cliente"]


async def test_ver_endpoint_de_muchos_reportes_dice_como_acotar(armar):
    env = armar(spec=spec_grande(600))
    out = await env.llamar("ver_endpoint", path="reports")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "601" in out  # 600 del spec grande + ACOrdenesCompraPendientes
    assert "buscar_endpoint" in out


async def test_leer_ancho_abrevia_columnas_y_lo_dice(armar):
    ancho = {f"Campo{j:03d}": "v" for j in range(800)}
    env = armar(lambda *a: [dict(ancho, Codigo=str(i)) for i in range(20)])
    out = await env.llamar("leer", path="anchos")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "columnas más" in out


# ------------------------------------------------------------------ leer


async def test_leer_chico_devuelve_json_y_carga_tabla(armar):
    uno = _cliente("P01093")
    env = armar(lambda *a: uno)
    out = await env.llamar("leer", path="cliente", id="P01093")
    assert '"Codigo": "P01093"' in out
    assert "cliente_p01093" in out
    assert env.workspace.crudo("cliente_p01093") == uno


async def test_leer_grande_devuelve_resumen(armar):
    env = armar(lambda *a: CLIENTES)
    out = await env.llamar("leer", path="cliente/list")
    assert "4150" in out
    assert "cliente" in out
    assert "P00099" not in out
    assert len(out) <= RESPUESTA_MAX_CHARS
    filas = await env.llamar("consultar", sql="SELECT count(*) AS n FROM cliente")
    assert "4150" in filas


async def test_leer_usa_el_nombre_de_tabla_pedido(armar):
    env = armar(lambda *a: CLIENTES[:2])
    out = await env.llamar("leer", path="cliente/list", tabla="mis_clientes")
    assert "mis_clientes" in out
    assert len(env.workspace.crudo("mis_clientes")) == 2


async def test_leer_pasa_params_tal_cual(armar):
    env = armar(lambda *a: [])
    params = {"PARAMWEBREPORT_Moneda": "PES"}
    await env.llamar("leer", path="reports/ACOrdenesCompraPendientes", params=params)
    assert env.cliente.llamadas[-1].params == {"PARAMWEBREPORT_Moneda": "PES"}


async def test_leer_siempre_usa_get(armar):
    env = armar(lambda *a: {"Codigo": "X"})
    await env.llamar("leer", path="cliente", id="X")
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


@pytest.mark.parametrize("respuesta", [[], [1, 2, 3], "texto plano", None])
async def test_leer_respuestas_raras_no_rompen(armar, respuesta):
    env = armar(lambda *a: respuesta)
    out = await env.llamar("leer", path="raro")
    assert out.strip()
    assert len(out) <= RESPUESTA_MAX_CHARS


async def test_leer_error_se_traduce_y_redacta(armar):
    def falla(*a):
        raise error_con_secreto(env.settings)

    env = armar(falla)
    out = await env.llamar("leer", path="cliente", id="X")
    assert CLIENT_SECRET not in out and CLIENT_ID not in out
    assert "Finnegans no pudo procesar" in out


# ------------------------------------------------------- consultar/exportar


async def test_consultar_pagina(armar):
    env = armar(lambda *a: CLIENTES)
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("consultar", sql="SELECT Codigo FROM cliente ORDER BY Codigo")
    assert "de 4150" in out
    assert "desde=" in out


async def test_consultar_rechaza_escrituras(armar):
    env = armar()
    out = await env.llamar("consultar", sql="DROP TABLE x")
    assert "lectura" in out


async def test_exportar_escribe_archivo_y_devuelve_ruta_y_filas(armar):
    env = armar(lambda *a: CLIENTES)
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("exportar", sql="SELECT Codigo, Nombre FROM cliente",
                           formato="csv", nombre="clientes")
    ruta = Path(env.settings.export_dir) / "clientes.csv"
    assert ruta.exists()
    assert str(ruta) in out
    assert "4150" in out


async def test_exportar_sin_nombre_usa_timestamp(armar):
    env = armar(lambda *a: CLIENTES[:3])
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("exportar", sql="SELECT * FROM cliente")
    archivos = list(Path(env.settings.export_dir).glob("finnegans-*.xlsx"))
    assert len(archivos) == 1
    assert archivos[0].name in out


async def test_exportar_con_mas_filas_que_el_tope_lo_dice(armar, monkeypatch):
    from finnegans_core import workspace as modulo

    monkeypatch.setattr(modulo, "MAX_FILAS_EXPORT", 100)
    env = armar(lambda *a: CLIENTES)
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("exportar", sql="SELECT Codigo FROM cliente ORDER BY Codigo",
                           formato="csv", nombre="tope")
    ruta = Path(env.settings.export_dir) / "tope.csv"
    assert len(ruta.read_text(encoding="utf-8-sig").splitlines()) == 101  # encabezado + 100
    assert "exporté 100 filas" in out
    assert "más de 100 filas" in out and "WHERE" in out


async def test_exportar_formato_invalido(armar):
    env = armar(lambda *a: CLIENTES[:3])
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("exportar", sql="SELECT * FROM cliente", formato="pdf")
    assert "xlsx" in out and "csv" in out


# --------------------------------------------------------------- escribir


def _handler_put(base: dict, releido: dict, respuesta_put=None):
    def handler(metodo, path, id, params, body):
        if metodo == "GET":
            return releido if any(c.metodo == "PUT" for c in handler.env.cliente.llamadas) \
                else base
        if metodo == "PUT":
            return respuesta_put if respuesta_put is not None else "OK"
        return None
    return handler


async def test_escribir_put_con_base_y_cambios(armar):
    base = _cliente("P01093", NroInscripcionIIBB="")
    releido = dict(copy.deepcopy(base), Nombre="Nuevo nombre",
                   NroInscripcionIIBB="20123456789")
    h = _handler_put(base, releido)
    env = armar(h)
    h.env = env
    await env.llamar("leer", path="cliente", id="P01093")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P01093",
                           base="cliente_p01093", cambios={"Nombre": "Nuevo nombre"})

    put = [c for c in env.cliente.llamadas if c.metodo == "PUT"]
    assert len(put) == 1
    esperado = dict(copy.deepcopy(base), Nombre="Nuevo nombre")
    assert put[0].body == esperado
    assert put[0].id == "P01093"

    gets = [c for c in env.cliente.llamadas if c.metodo == "GET"]
    assert len(gets) == 2  # leer + relectura despues del PUT
    assert gets[-1].id == "P01093"

    cambiados, por_su_cuenta = _secciones(out)
    assert "Campos cambiados" in cambiados
    assert "Nombre" in cambiados
    assert "NroInscripcionIIBB" in por_su_cuenta
    assert "Nombre" not in por_su_cuenta
    # La base no se modifica en el lugar: el crudo del workspace queda fiel.
    assert env.workspace.crudo("cliente_p01093")["NroInscripcionIIBB"] == "20123456789"


async def test_escribir_base_actualizada_tras_releer(armar):
    base = _cliente("P01093")
    releido = dict(copy.deepcopy(base), Nombre="Otro")
    h = _handler_put(base, releido)
    env = armar(h)
    h.env = env
    await env.llamar("leer", path="cliente", id="P01093")
    await env.llamar("escribir", metodo="PUT", path="cliente", id="P01093",
                     base="cliente_p01093", cambios={"Nombre": "Otro"})
    assert env.workspace.crudo("cliente_p01093") == releido


async def test_escribir_post_relee_con_codigo_del_body(armar):
    nuevo = _cliente("ZZ-PRUEBA")
    env = armar(lambda m, p, i, pa, b: nuevo if m == "GET" else "OK")
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=nuevo)
    gets = [c for c in env.cliente.llamadas if c.metodo == "GET"]
    assert len(gets) == 1 and gets[0].id == "ZZ-PRUEBA" and gets[0].path == "cliente"
    assert "Campos que la API cambió por su cuenta" in out


async def test_escribir_post_usa_el_codigo_que_asigna_finnegans(armar):
    # Finnegans ignora el Codigo del body en el alta y devuelve el suyo en "id".
    enviado = _cliente("ZZ-PRUEBA-MCP")
    guardado = dict(copy.deepcopy(enviado), Codigo="2956")

    def handler(metodo, path, id, params, body):
        if metodo == "POST":
            return {"id": "2956", "message": "created", "status": 200}
        if metodo == "GET" and id == "2956":
            return guardado
        from finnegans_core.client import FinnegansError
        raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")

    env = armar(handler)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=enviado)
    gets = [c for c in env.cliente.llamadas if c.metodo == "GET"]
    assert len(gets) == 1 and gets[0].id == "2956" and gets[0].path == "cliente"
    assert "Finnegans ignoró el Codigo enviado 'ZZ-PRUEBA-MCP' y le asignó '2956'" in out
    _, por_su_cuenta = _secciones(out)
    assert "Codigo: ZZ-PRUEBA-MCP → 2956" in por_su_cuenta
    assert "quedó con el código 2956" in out
    assert "no pude releer" not in out


async def test_escribir_post_id_igual_al_codigo_no_dice_que_lo_ignoro(armar):
    nuevo = _cliente("2956")
    env = armar(lambda m, p, i, pa, b: nuevo if m == "GET" else {"ID": 2956})
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=nuevo)
    assert "le asignó al registro nuevo el código '2956'" in out
    assert "ignoró" not in out
    assert [c.id for c in env.cliente.llamadas if c.metodo == "GET"] == ["2956"]


async def test_escribir_post_relectura_del_codigo_asignado_fallida(armar):
    def handler(metodo, path, id, params, body):
        if metodo == "POST":
            return {"id": "2956", "message": "created"}
        from finnegans_core.client import FinnegansError
        raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")

    env = armar(handler)
    out = await env.llamar("escribir", metodo="POST", path="cliente",
                           body=_cliente("ZZ-PRUEBA-MCP"))
    assert "asignó" not in out
    assert "no sé con qué código quedó el registro" in out
    assert "la API devolvió id '2956'" in out
    assert "Antes de cualquier PUT o DELETE" in out
    assert "Campos que la API cambió por su cuenta" not in out
    assert [c.id for c in env.cliente.llamadas if c.metodo == "GET"] == [
        "2956", "ZZ-PRUEBA-MCP"]


async def test_escribir_post_id_404_relee_con_el_codigo_enviado(armar):
    enviado = _cliente("ZZ-PRUEBA-MCP")
    guardado = dict(copy.deepcopy(enviado), Nombre="Normalizado")

    def handler(metodo, path, id, params, body):
        if metodo == "POST":
            return {"id": "88123", "message": "created"}
        if metodo == "GET" and id == "ZZ-PRUEBA-MCP":
            return guardado
        from finnegans_core.client import FinnegansError
        raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")

    env = armar(handler)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=enviado)
    assert [c.id for c in env.cliente.llamadas if c.metodo == "GET"] == [
        "88123", "ZZ-PRUEBA-MCP"]
    assert "asignó" not in out
    assert "lo releí con el Codigo enviado 'ZZ-PRUEBA-MCP'" in out
    _, por_su_cuenta = _secciones(out)
    assert "Normalizado" in por_su_cuenta


async def test_escribir_post_id_que_relee_otro_registro_no_muestra_su_diff(armar):
    # El id de la respuesta es interno: con el se lee un registro de otro codigo.
    enviado = _cliente("ZZ-PRUEBA-MCP")
    ajeno = _cliente("P00077", Nombre="Registro ajeno")

    def handler(metodo, path, id, params, body):
        if metodo == "POST":
            return {"id": "77", "message": "created"}
        if metodo == "GET" and id == "77":
            return ajeno
        from finnegans_core.client import FinnegansError
        raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")

    env = armar(handler)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=enviado)
    assert [c.id for c in env.cliente.llamadas if c.metodo == "GET"] == [
        "77", "ZZ-PRUEBA-MCP"]
    assert "asignó" not in out
    assert "Campos que la API cambió por su cuenta" not in out
    assert "P00077" not in out and "Registro ajeno" not in out
    assert "no sé con qué código quedó el registro" in out
    assert "la API devolvió id '77'" in out
    assert "leer o consultar" in out


async def test_escribir_post_sin_id_en_la_respuesta_relee_con_el_body(armar):
    nuevo = _cliente("ZZ-PRUEBA")
    env = armar(lambda m, p, i, pa, b: nuevo if m == "GET" else {"message": "created"})
    out = await env.llamar("escribir", metodo="POST", path="cliente", body=nuevo)
    assert [c.id for c in env.cliente.llamadas if c.metodo == "GET"] == ["ZZ-PRUEBA"]
    assert "asignó" not in out


async def test_leer_y_escribir_aceptan_id_numerico(armar):
    registro = _cliente("2956")
    env = armar(lambda m, *a: registro if m == "GET" else {"message": "updated"})
    r = await env.server.call_tool("leer", {"path": "cliente", "id": 2956})
    assert not r.is_error, r
    assert env.cliente.llamadas[-1].id == "2956"
    r = await env.server.call_tool("escribir", {
        "metodo": "PUT", "path": "cliente", "id": 2956,
        "base": "cliente_2956", "cambios": {"Nombre": "Otro"}})
    assert not r.is_error, r
    texto = "".join(c.text for c in r.content)
    assert "Finnegans aceptó" in texto
    put = [c for c in env.cliente.llamadas if c.metodo == "PUT"]
    assert len(put) == 1 and put[0].id == "2956"
    r = await env.server.call_tool("escribir", {"metodo": "DELETE", "path": "cliente",
                                                "id": 2956})
    assert not r.is_error, r
    assert env.cliente.llamadas[-1].metodo == "DELETE"
    assert env.cliente.llamadas[-1].id == "2956"


async def test_escribir_viewer_no_relee(armar):
    env = armar(lambda *a: "OK")
    await env.llamar("escribir", metodo="POST", path="reports/ACOrdenesCompraPendientes",
                     body={"Codigo": "X"})
    assert [c.metodo for c in env.cliente.llamadas] == ["POST"]


async def test_escribir_pasa_params(armar):
    env = armar(lambda m, *a: {"Codigo": "X"} if m == "GET" else "OK")
    await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                     body={"Codigo": "X"}, params={"createIfNotExists": "1"})
    assert env.cliente.llamadas[0].params == {"createIfNotExists": "1"}


async def test_escribir_delete_devuelve_estado(armar):
    env = armar(lambda *a: None)
    out = await env.llamar("escribir", metodo="DELETE", path="cliente", id="P01093")
    assert [c.metodo for c in env.cliente.llamadas] == ["DELETE"]
    assert "elimin" in out.lower()
    assert "Campos cambiados" not in out


async def test_escribir_error_no_filtra_secretos(armar):
    def falla(*a):
        raise error_con_secreto(env.settings)

    env = armar(falla)
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert CLIENT_SECRET not in out and CLIENT_ID not in out
    assert "***" in out or "Finnegans no pudo procesar" in out
    assert "Finnegans no pudo procesar la operacion sobre 'cliente'" in out


async def test_escribir_error_desconocido_redacta_el_detalle(armar):
    def falla(*a):
        from finnegans_core.client import FinnegansError
        raise FinnegansError(f"Error en PUT cliente (HTTP 406): token {CLIENT_SECRET}")

    env = armar(falla)
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert CLIENT_SECRET not in out
    assert "***" in out


async def test_escribir_base_inexistente(armar):
    env = armar()
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           base="nope", cambios={"Nombre": "x"})
    assert "leer" in out
    assert "nope" in out
    assert env.cliente.llamadas == []


async def test_escribir_base_con_varios_registros_pide_uno(armar):
    env = armar(lambda *a: CLIENTES[:5])
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P00001",
                           base="cliente", cambios={"Nombre": "x"})
    assert "leer(" in out and "id=" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_escribir_body_y_base_juntos_es_error_claro(armar):
    env = armar(lambda *a: _cliente("X"))
    await env.llamar("leer", path="cliente", id="X")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"}, base="cliente_x", cambios={"Nombre": "y"})
    assert "base" in out and "body" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_escribir_metodo_invalido(armar):
    env = armar()
    out = await env.llamar("escribir", metodo="GET", path="cliente", id="X")
    assert "leer" in out
    assert env.cliente.llamadas == []


async def test_escribir_body_no_serializable_no_rompe(armar):
    def falla(*a):
        raise TypeError("Object of type datetime is not JSON serializable")

    env = armar(falla)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body={"Codigo": "X"})
    assert "JSON" in out
    assert "no se envió" in out.lower()


async def test_escribir_relectura_fallida_avisa_que_la_escritura_se_hizo(armar):
    def handler(metodo, *a):
        if metodo == "GET":
            from finnegans_core.client import FinnegansError
            raise FinnegansError("No se pudo conectar a Finnegans (cliente): timeout")
        return "OK"

    env = armar(handler)
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert "se hizo" in out.lower() or "se ejecutó" in out.lower()
    assert "releer" in out.lower()


# --------------------------------------------------- busqueda/ver/guia


async def test_buscar_endpoint_sin_claves_de_docs_sigue(armar, tmp_path):
    s = ajustes(tmp_path, docs_client_id="", docs_secret_key="")
    env = armar(settings=s, usar_docs_real=True)
    out = await env.llamar("buscar_endpoint", consulta="ordenes de compra pendientes")
    assert "/reports/ACOrdenesCompraPendientes" in out
    assert "solo con el swagger" in out


async def test_buscar_endpoint_error_de_swagger_es_mensaje(armar):
    env = armar(status_swagger=401)
    out = await env.llamar("buscar_endpoint", consulta="cliente")
    assert SWAGGER_KEY not in out
    assert "swagger" in out.lower()


async def test_ver_endpoint_muestra_parametros_y_body(armar):
    env = armar()
    out = await env.llamar("ver_endpoint", path="cliente")
    assert "PUT" in out and "createIfNotExists" in out
    assert "ProvinciaItems" in out and "Nombre" in out
    assert SWAGGER_KEY not in out and "abc123" not in out


async def test_ver_endpoint_campo_expande_un_nivel(armar):
    env = armar()
    out = await env.llamar("ver_endpoint", path="cliente", campo="ProvinciaItems")
    assert "ControlImpositivo1" in out and "Provincia" in out


async def test_ver_endpoint_inexistente(armar):
    env = armar()
    out = await env.llamar("ver_endpoint", path="nada")
    assert "buscar_endpoint" in out


async def test_guia_lista_y_tema(armar):
    env = armar()
    assert "escrituras" in await env.llamar("guia")
    assert (await env.llamar("guia", tema="escrituras")).startswith("#")


# ------------------------------------------------------- verificar_conexion


async def test_verificar_conexion_nombra_la_clave_mala(armar, tmp_path):
    # Claves faltantes: se nombran con las etiquetas del formulario.
    s = ajustes(tmp_path, client_secret="", docs_secret_key="")
    env = armar(settings=s)
    out = await env.llamar("verificar_conexion")
    for etiqueta in s.faltantes():
        assert etiqueta in out

    # Token rechazado: la clave mala es el par de Finnegans.
    env = armar(error_token=FinnegansAuthError(
        "Fallo la autenticacion (HTTP 401). Revisa el Client ID y el Client secret."))
    out = await env.llamar("verificar_conexion")
    assert "Client ID / secret de Finnegans" in out

    # La documentacion falla, pero el swagger sigue OK.
    docs = DocsFalso(error=DocsMcpError(f"No se pudo consultar la documentación ({DOCS_KEY})"))
    env = armar(docs=docs)
    out = await env.llamar("verificar_conexion")
    assert "documentación" in out
    assert DOCS_KEY not in out
    linea_swagger = next(l for l in out.splitlines() if "swagger" in l.lower())
    assert "OK" in linea_swagger


async def test_verificar_conexion_todo_ok(armar):
    env = armar()
    out = await env.llamar("verificar_conexion")
    assert out.count("OK") >= 3


async def test_verificar_conexion_swagger_rechazado(armar):
    env = armar(status_swagger=401)
    out = await env.llamar("verificar_conexion")
    assert "Clave del swagger" in out
    assert SWAGGER_KEY not in out


async def test_los_logs_http_no_muestran_claves(armar, caplog):
    import logging
    # Como en produccion: el MCPServer deja el logging raiz en INFO.
    caplog.set_level(logging.INFO)
    logging.getLogger("httpx2").setLevel(logging.NOTSET)
    env = armar()
    await env.llamar("verificar_conexion")
    await env.llamar("buscar_endpoint", consulta="cliente")
    assert logging.getLogger("httpx2").getEffectiveLevel() >= logging.WARNING
    assert SWAGGER_KEY not in caplog.text
    assert CLIENT_SECRET not in caplog.text


async def test_error_inesperado_despues_de_escribir_avisa_que_se_escribio(armar, monkeypatch):
    import finnegans_mcp.server as srv

    def roto(*a, **k):
        raise RuntimeError(f"roto {CLIENT_SECRET}")

    monkeypatch.setattr(srv, "diff", roto)
    env = armar(lambda m, *a: {"Codigo": "X"} if m == "GET" else "OK")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert "aceptó la escritura" in out
    assert "leer" in out
    assert CLIENT_SECRET not in out


async def test_error_inesperado_en_leer_no_llega_crudo(armar):
    def roto(*a):
        raise RuntimeError(f"explota con {CLIENT_SECRET}")

    env = armar(roto)
    out = await env.llamar("leer", path="cliente")
    assert "inesperado" in out
    assert CLIENT_SECRET not in out and "***" in out


# ------------------------------------------------------ fix round 1


def _vo_ancho(n=400, requeridos=("Codigo", "Nombre", "CampoLargoNombre399")):
    """VO de 400 campos con nombres de largo real: su detalle no entra entero."""
    props = {"Codigo": {"type": "string"}, "Nombre": {"type": "string"}}
    props.update({f"CampoLargoNombre{j:03d}": {"type": "string"} for j in range(n)})
    props["ProvinciaItems"] = {"type": "array", "items": {"type": "object", "properties": {
        "Provincia": {"type": "string"}}}}
    return {"ClienteVO": {"required": list(requeridos), "properties": props}}


async def test_ver_endpoint_vo_ancho_muestra_requeridos_y_como_seguir(armar):
    env = armar(vos=_vo_ancho())
    out = await env.llamar("ver_endpoint", path="/cliente/{codigo}")
    assert len(out) <= RESPUESTA_MAX_CHARS
    # Los requeridos aparecen aunque esten al final del schema.
    assert "Codigo*" in out and "Nombre*" in out and "CampoLargoNombre399*" in out
    assert "createIfNotExists" in out
    assert "campos más" in out
    assert "metodo='PUT'" in out
    # Nunca manda a repetir la misma llamada.
    assert "ver_endpoint('/cliente/{codigo}')" not in out


async def test_ver_endpoint_con_metodo_muestra_una_operacion_entera(armar):
    env = armar(vos=_vo_ancho())
    out = await env.llamar("ver_endpoint", path="cliente", metodo="put")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "PUT /cliente/{codigo}" in out
    assert "DELETE /cliente" not in out and "POST /cliente" not in out
    assert "CampoLargoNombre000" in out and "CampoLargoNombre250" in out
    # Si aun asi no entra, no propone repetir la misma llamada.
    assert "metodo='PUT')" not in out


async def test_ver_endpoint_metodo_inexistente(armar):
    env = armar()
    out = await env.llamar("ver_endpoint", path="/reports/ACOrdenesCompraPendientes",
                           metodo="PUT")
    assert "GET" in out


async def test_ver_endpoint_campo_con_metodo(armar):
    env = armar()
    out = await env.llamar("ver_endpoint", path="cliente", campo="ProvinciaItems",
                           metodo="POST")
    assert "POST" in out and "ControlImpositivo1" in out


async def test_ver_endpoint_muchas_operaciones_no_repite_la_llamada(armar):
    env = armar(spec=spec_grande(600))
    out = await env.llamar("ver_endpoint", path="reports")
    assert "ver_endpoint('reports')" not in out


async def test_escribir_base_de_otro_registro_se_rechaza(armar):
    env = armar(lambda *a: _cliente("P01093"))
    await env.llamar("leer", path="cliente", id="P01093")
    for args in (
        dict(id="P99999", path="cliente"),
        dict(path="cliente/P99999"),
    ):
        out = await env.llamar("escribir", metodo="PUT", base="cliente_p01093",
                               cambios={"Nombre": "x"}, **args)
        assert "P01093" in out and "P99999" in out
        assert "No se envió nada" in out
    # cambiar Codigo en cambios no disfraza que la base es otro registro
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P99999",
                           base="cliente_p01093", cambios={"Codigo": "P99999"})
    assert "No se envió nada" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_escribir_body_con_otro_codigo_se_rechaza(armar):
    env = armar()
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="B",
                           body={"Codigo": "A"})
    assert "No se envió nada" in out
    assert env.cliente.llamadas == []


async def test_escribir_timeout_no_invita_a_reintentar(armar):
    from finnegans_core.client import FinnegansError

    def corta(*a):
        raise FinnegansError("No se pudo conectar a Finnegans (cliente): timed out")

    env = armar(corta)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body={"Codigo": "N1"})
    assert "puede haberse aplicado" in out
    assert "leer" in out and "N1" in out
    assert "falló" not in out
    assert "Volve a intentar" not in out and "Volvé a intentar" not in out


async def test_escribir_http_error_dice_fallo(armar):
    from finnegans_core.client import FinnegansError

    def rechaza(*a):
        raise FinnegansError("Error en POST cliente (HTTP 500): boom")

    env = armar(rechaza)
    out = await env.llamar("escribir", metodo="POST", path="cliente", body={"Codigo": "N1"})
    assert "falló" in out
    assert "puede haberse aplicado" not in out


async def test_secreto_que_cruza_el_corte_no_deja_prefijo(armar):
    from finnegans_core.client import FinnegansError
    prefijo = CLIENT_SECRET[:10]

    # Respuesta de la API cortada a 300 caracteres.
    respuesta = "x" * 285 + CLIENT_SECRET + "y" * 50
    env = armar(lambda m, *a: respuesta)
    out = await env.llamar("escribir", metodo="PATCH", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert prefijo not in out

    # Detalle tecnico de traducir_error, cortado a 300.
    cab = "Error en PUT cliente (HTTP 406): "
    crudo = cab + "x" * (285 - len(cab)) + CLIENT_SECRET

    def falla(*a):
        raise FinnegansError(crudo)

    env = armar(falla)
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="X",
                           body={"Codigo": "X"})
    assert prefijo not in out

    # Error de la documentacion en verificar_conexion, cortado a 300.
    docs = DocsFalso(error=DocsMcpError("d" * 280 + DOCS_KEY + "z" * 40))
    env = armar(docs=docs)
    out = await env.llamar("verificar_conexion")
    assert DOCS_KEY[:10] not in out


async def test_escribir_rechaza_base_de_un_listado(armar):
    env = armar(lambda m, p, *a: [_cliente("P01093")] if p == "cliente/list" else {})
    await env.llamar("leer", path="cliente/list")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P01093",
                           base="cliente", cambios={"Nombre": "x"})
    assert "leer(" in out and "id=" in out
    assert "No se envió nada" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_escribir_rechaza_base_de_un_reporte(armar):
    env = armar(lambda *a: _cliente("P01093"))
    await env.llamar("leer", path="reports/ACOrdenesCompraPendientes", tabla="rep")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P01093",
                           base="rep", cambios={"Nombre": "x"})
    assert "No se envió nada" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_leer_muestra_y_nota_redactan_antes_de_cortar(armar):
    prefijo = CLIENT_SECRET[:10]
    filas = [{"Codigo": str(i), "Texto": "x" * 105 + CLIENT_SECRET} for i in range(2000)]
    env = armar(lambda *a: filas)
    out = await env.llamar("leer", path="cliente/list")
    assert "Muestra" in out
    assert prefijo not in out
    env = armar(lambda *a: "x" * 490 + CLIENT_SECRET + "y" * 9000)
    out = await env.llamar("leer", path="texto")
    assert prefijo not in out


async def test_codigo_en_minusculas_tambien_se_compara(armar):
    env = armar(lambda *a: {"codigo": "P01093", "Nombre": "A"})
    await env.llamar("leer", path="cliente", id="P01093")
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="P99999",
                           base="cliente_p01093", cambios={"Nombre": "x"})
    assert "No se envió nada" in out and "P01093" in out
    out = await env.llamar("escribir", metodo="PUT", path="cliente", id="B",
                           body={"CODIGO": "A"})
    assert "No se envió nada" in out
    assert [c.metodo for c in env.cliente.llamadas] == ["GET"]


async def test_leer_404_con_codigo_en_el_path_sugiere_el_listado_correcto(armar):
    def handler(*a):
        from finnegans_core.client import FinnegansError
        raise FinnegansError("Error en GET cliente/2956 (HTTP 404): no existe")

    env = armar(handler)
    out = await env.llamar("leer", path="cliente/2956")
    assert "No existe 'cliente/2956'" in out
    assert "'cliente/list'" in out and "cliente/2956/list" not in out
