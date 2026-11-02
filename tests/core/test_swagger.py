"""Catalogo del swagger: busqueda, tipos de endpoint y resolucion de refs."""
import json

import httpx2
import pytest

from finnegans_core.catalogo import swagger as sw
from finnegans_core.catalogo.swagger import SwaggerCatalog, SwaggerError
from finnegans_core.config import Settings

KEY = "k3y-secreta-9f8e7d"
SWAGGER_URL = "https://oneteam.finneg.com/BSA/api/swaggerGlobal"


def _settings(**extra):
    env = {"FINNEGANS_SWAGGER_KEY": KEY, "FINNEGANS_SWAGGER_URL": SWAGGER_URL}
    env.update(extra)
    return Settings.from_env(env)


class Red:
    """Transporte falso: sirve el spec y los VO, y registra cada pedido."""

    def __init__(self, spec, vos=None, falla_vo=False):
        self.spec = spec
        self.vos = vos or {}
        self.falla_vo = falla_vo
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(req)
        if req.url.path.endswith("swaggerGlobal"):
            return httpx2.Response(200, json=self.spec)
        if self.falla_vo:
            raise httpx2.ConnectError("sin red")
        vo = self.vos.get(req.url.params.get("nombreVO"))
        if vo is None:
            return httpx2.Response(404, text="no existe")
        return httpx2.Response(200, json=vo)

    def catalogo(self, **extra):
        http = httpx2.Client(transport=httpx2.MockTransport(self))
        return SwaggerCatalog(_settings(**extra), http=http)

    def pedidos_vo(self):
        return [r for r in self.pedidos if not r.url.path.endswith("swaggerGlobal")]


def _op(tags, summary="", opid="", params=None):
    d = {"tags": tags, "summary": summary, "operationId": opid}
    if params is not None:
        d["parameters"] = params
    return d


REF_CLIENTE = "/BSA/api/swaggerApi?key=abc123&api=cliente&nombreVO=ClienteVO"

VO_CLIENTE = {
    "required": ["Codigo", "Nombre"],
    "properties": {
        "Codigo": {"type": "string"},
        "Nombre": {"type": "string"},
        "Descripcion": {"type": "string"},
        "ProvinciaItems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ControlImpositivo1": {"type": "string"},
                    "Provincia": {"type": "string"},
                },
            },
        },
    },
}

SPEC = {
    "swagger": "2.0",
    "basePath": "/api",
    "tags": [
        {"name": "Autenticacion OAuth 2.0", "description": "Obtencion de access_token"},
        {"name": "cliente", "description": "Entidad cliente. Tipo: EntidadVO"},
        {"name": "movimientoFondos", "description": "Tipo: EntidadVO"},
        {"name": "ACOrdenesCompraPendientes", "description": "Reporte. Tipo: Viewer"},
        {"name": "analisisFacturaVenta", "description": "Reporte. Tipo: Viewer"},
        {"name": "raro", "description": "Esta en reports pero Tipo: EntidadVO"},
    ],
    "definitions": {
        "ParametroToken": {"name": "ACCESS_TOKEN", "in": "query", "required": True,
                           "description": "Token"},
        "ParametroCodigo": {"name": "codigo", "in": "path", "required": True,
                            "description": "Codigo de la entidad"},
        "ParametroForceInsert": {"name": "createIfNotExists", "in": "query",
                                 "required": False, "description": "Crear si no existe"},
        "ParametroUpdateSince": {"name": "updatedSince", "in": "query", "required": False,
                                 "description": "Desde ultima actualizacion"},
    },
    "paths": {
        "/oauth/token": {"get": _op(["Autenticacion OAuth 2.0"], "token", "oauth_token")},
        "/cliente": {
            "post": _op(["cliente"], "cliente", "cliente_post",
                        [{"name": "ClienteVO", "in": "body", "required": True,
                          "schema": {"$ref": REF_CLIENTE}}]),
        },
        "/cliente/list": {
            "get": _op(["cliente"], "cliente", "cliente_list",
                       [{"$ref": "#/definitions/ParametroUpdateSince"}]),
            "parameters": [{"$ref": "#/definitions/ParametroToken"}],
        },
        "/cliente/{codigo}": {
            "get": _op(["cliente"], "cliente", "cliente_get", []),
            "put": _op(["cliente"], "cliente", "cliente_put",
                       [{"name": "ClienteVO", "in": "body", "required": True,
                         "schema": {"$ref": REF_CLIENTE}},
                        {"$ref": "#/definitions/ParametroForceInsert"}]),
            "parameters": [{"$ref": "#/definitions/ParametroToken"},
                           {"$ref": "#/definitions/ParametroCodigo"}],
        },
        "/reports/ACOrdenesCompraPendientes": {"get": _op(
            ["ACOrdenesCompraPendientes"], "ACOrdenesCompraPendientes",
            "reports_ACOrdenesCompraPendientes",
            [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
             {"name": "PARAM_Fechadesde", "in": "query", "required": False,
              "description": "Fecha desde"}])},
        "/reports/analisisFacturaVenta": {"get": _op(
            ["analisisFacturaVenta"], "Analisis de facturas de venta",
            "reports_analisisFacturaVenta",
            [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
             {"name": "FechaDesde", "in": "query", "required": False,
              "description": "Filtrar por fecha desde"}])},
        "/reports/raro": {"get": _op(["raro"], "raro", "reports_raro")},
        "/movimientoFondos": {"post": _op(["movimientoFondos"], "movimientoFondos",
                                          "movimientoFondos_post")},
        "/movimientoFondos/{codigo}": {"get": _op(["movimientoFondos"], "movimientoFondos",
                                                  "movimientoFondos_get")},
    },
}

VOS = {"ClienteVO": VO_CLIENTE}


@pytest.fixture
def red():
    return Red(SPEC, VOS)


@pytest.fixture
def cat(red):
    return red.catalogo()


def _catalogo_de(paths, tags=None):
    spec = {"swagger": "2.0", "tags": tags or [], "paths": paths}
    return Red(spec).catalogo()


def _ep(nombre, path=None):
    return {path or f"/{nombre}": {"get": _op([nombre], nombre, f"{nombre}_get")}}


def _paths(cat, consulta):
    return [c.path for c in cat.buscar(consulta)]


# ------------------------------------------------------------------ carga

def test_spec_arma_la_url_con_la_key_y_se_cachea(red, cat):
    a = cat.spec()
    b = cat.spec()
    assert a is b
    assert len(red.pedidos) == 1
    assert red.pedidos[0].url.params["key"] == KEY
    assert str(red.pedidos[0].url).startswith(SWAGGER_URL)


def test_spec_se_cachea_por_proceso_entre_instancias(red):
    red.catalogo().spec()
    red.catalogo().spec()
    assert len(red.pedidos) == 1


def test_key_con_caracteres_raros_va_codificada():
    red = Red(SPEC)
    red.catalogo(FINNEGANS_SWAGGER_KEY="k e/y").spec()
    assert "key=k%20e%2Fy" in str(red.pedidos[0].url) or "key=k+e%2Fy" in str(red.pedidos[0].url)


def test_error_de_red_es_swaggererror():
    def h(req):
        raise httpx2.ConnectError("sin red")

    cat = SwaggerCatalog(_settings(), http=httpx2.Client(transport=httpx2.MockTransport(h)))
    with pytest.raises(SwaggerError):
        cat.spec()


def test_http_de_error_y_json_invalido_son_swaggererror():
    for resp in (httpx2.Response(500, text="boom"), httpx2.Response(200, text="<html>")):
        cat = SwaggerCatalog(
            _settings(), http=httpx2.Client(transport=httpx2.MockTransport(lambda r, x=resp: x))
        )
        with pytest.raises(SwaggerError):
            cat.spec()


def test_sin_key_es_swaggererror_claro():
    cat = SwaggerCatalog(Settings.from_env({}), http=httpx2.Client(
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={}))))
    with pytest.raises(SwaggerError, match="clave"):
        cat.spec()


def test_errores_de_carga_no_filtran_la_key():
    def h(req):
        # httpx2 incluye la URL (con la key) en el texto de muchos errores.
        raise httpx2.ConnectError(f"fallo al conectar con {req.url}")

    cat = SwaggerCatalog(_settings(), http=httpx2.Client(transport=httpx2.MockTransport(h)))
    with pytest.raises(SwaggerError) as e:
        cat.spec()
    assert KEY not in str(e.value)
    assert "***" in str(e.value)

    def h500(req):
        return httpx2.Response(500, text=f"error en {req.url}")

    cat = SwaggerCatalog(_settings(), http=httpx2.Client(transport=httpx2.MockTransport(h500)))
    with pytest.raises(SwaggerError) as e:
        cat.spec()
    assert KEY not in str(e.value)


# ------------------------------------------------------------------- tipo

def test_tipo_sale_del_tag_y_no_del_path(cat):
    assert cat.tipo("/reports/ACOrdenesCompraPendientes") == "viewer"
    assert cat.tipo("/cliente/{codigo}") == "entidad"
    assert cat.tipo("/oauth/token") == "otro"
    # Un path en /reports cuyo tag dice EntidadVO es una entidad.
    assert cat.tipo("/reports/raro") == "entidad"


def test_tipo_de_un_path_desconocido_es_otro(cat):
    assert cat.tipo("/no/existe") == "otro"


# ----------------------------------------------------------------- tokens

def test_tokens_parte_camelcase_y_conserva_el_token_completo():
    assert sw._tokens("movimientoFondos") == ["movimientofondos", "movimiento", "fondos"]


def test_tokens_siglas_pegadas_a_palabra():
    assert sw._tokens("getAPIDatos") == ["getapidatos", "get", "api", "datos"]


def test_tokens_separadores_no_alfanumericos():
    assert sw._tokens("reports/ordenPago_list") == [
        "reports", "ordenpago", "orden", "pago", "list"]


def test_tokens_vacio_y_none():
    assert sw._tokens("") == []
    assert sw._tokens(None) == []


def test_tokens_la_tilde_no_parte_la_palabra():
    assert sw._tokens("tesorería") == sw._tokens("tesoreria") == ["tesoreria"]


# ----------------------------------------------------------------- buscar

def test_encuentra_cliente_y_rankea(cat):
    r = cat.buscar("cliente")
    paths = [c.path for c in r]
    assert "/cliente/list" in paths and "/cliente/{codigo}" in paths
    assert all(c.puntaje > 0 for c in r)
    assert r == sorted(r, key=lambda c: c.puntaje, reverse=True)


def test_encuentra_reporte_por_venta(cat):
    assert "/reports/analisisFacturaVenta" in _paths(cat, "factura de venta")


def test_sin_coincidencias_devuelve_vacio(cat):
    assert cat.buscar("zzz-inexistente") == []
    assert cat.buscar("") == []


def test_limite(cat):
    assert len(cat.buscar("cliente", limite=1)) == 1


def test_buscar_expone_tipo_y_cobertura(cat):
    primero = cat.buscar("ordenes compra pendientes")[0]
    assert primero.path == "/reports/ACOrdenesCompraPendientes"
    assert primero.tipo == "viewer"
    assert primero.cobertura == 1.0
    assert primero.metodos == ["GET"]
    assert cat.buscar("cliente marciano")[0].cobertura == 0.5


def test_coincidencia_trae_metodos_y_resumen(cat):
    c = next(c for c in cat.buscar("cliente") if c.path == "/cliente/{codigo}")
    assert c.metodos == ["GET", "PUT"]
    assert c.resumen == "cliente"
    assert c.tipo == "entidad"


def test_camelcase_movimiento_de_fondos(cat):
    paths = _paths(cat, "movimiento de fondos")
    assert "/movimientoFondos" in paths and "/movimientoFondos/{codigo}" in paths
    assert _paths(cat, "movimientoFondos")[0].startswith("/movimientoFondos")


def test_otros_recursos_camelcase():
    cat = _catalogo_de({**_ep("ordenPago", "/ordenPago/list"), **_ep("resumenBancario"),
                        **_ep("rendicionFondos", "/rendicionFondos/list")})
    for consulta, esperado in (("orden de pago", "/ordenPago/list"),
                               ("resumen bancario", "/resumenBancario"),
                               ("rendicion de fondos", "/rendicionFondos/list")):
        assert esperado in _paths(cat, consulta), consulta


def test_recurso_exacto_primero_sobre_reportes_que_lo_mencionan():
    cat = _catalogo_de({
        **_ep("cliente", "/cliente/list"),
        **_ep("getDatosClienteEmpresa", "/reports/getDatosClienteEmpresa"),
        **_ep("ConfigLimiteCreditoCliente", "/ConfigLimiteCreditoCliente/list"),
    })
    assert _paths(cat, "cliente")[0] == "/cliente/list"


def test_mas_coincidencias_gana_sobre_mas_precision():
    cat = _catalogo_de({**_ep("movimientoFondos"),
                        **_ep("rendicionFondos", "/rendicionFondos/list")})
    r = cat.buscar("movimiento fondos")
    exacto = next(c for c in r if c.path == "/movimientoFondos")
    parcial = next(c for c in r if c.path == "/rendicionFondos/list")
    assert exacto.puntaje > parcial.puntaje


VOCAB = {
    **_ep("movimientoFondos"), **_ep("ordenPago"), **_ep("cobranza"), **_ep("banco"),
    **_ep("resumenBancario"), **_ep("despacho"), **_ep("cliente", "/cliente/list"),
    **_ep("ApiSituacionCheques", "/reports/ApiSituacionCheques"),
    **_ep("stockDeposito", "/reports/stockDeposito"),
}


def test_vocabulario_acentos_plurales_y_sinonimos():
    cat = _catalogo_de(VOCAB)
    assert "/movimientoFondos" in _paths(cat, "tesorería")
    assert _paths(cat, "tesorería") == _paths(cat, "tesoreria")
    assert "/reports/ApiSituacionCheques" in _paths(cat, "cheque")
    assert _paths(cat, "cheque") == _paths(cat, "cheques")
    assert "/movimientoFondos" in _paths(cat, "caja")
    assert "/resumenBancario" in _paths(cat, "banco")
    assert "/despacho" in _paths(cat, "remito")
    assert "/reports/stockDeposito" in _paths(cat, "inventario")
    assert _paths(cat, "cliente")[0] == "/cliente/list"
    assert _paths(cat, "banco")[0] == "/banco"


def test_un_sinonimo_no_infla_la_cobertura():
    cat = _catalogo_de(VOCAB)
    assert cat.buscar("caja")[0].cobertura == 1.0


# -------------------------------------------------------------------- ver

def _ver(cat, recurso, metodo, path=None):
    return next(o for o in cat.ver(recurso)
                if o.metodo == metodo and (path is None or o.path == path))


def test_ver_operaciones_de_cliente(cat):
    pares = {(o.metodo, o.path) for o in cat.ver("cliente")}
    assert {("GET", "/cliente/list"), ("GET", "/cliente/{codigo}"),
            ("PUT", "/cliente/{codigo}"), ("POST", "/cliente")} <= pares
    assert all(o.tipo == "entidad" for o in cat.ver("cliente"))


def test_ver_acepta_path_exacto_con_o_sin_barra(cat):
    ops = cat.ver("reports/ACOrdenesCompraPendientes")
    assert len(ops) == 1 and ops[0].tipo == "viewer"
    assert len(cat.ver("/reports/ACOrdenesCompraPendientes")) == 1
    assert cat.ver("noexiste") == []


def test_params_excluyen_access_token_y_body(cat):
    op = _ver(cat, "cliente", "GET", "/cliente/{codigo}")
    nombres = [p["nombre"] for p in op.parametros]
    assert "codigo" in nombres and "ACCESS_TOKEN" not in nombres
    for op in cat.ver("cliente"):
        assert "ACCESS_TOKEN" not in [p["nombre"] for p in op.parametros]
        assert "ClienteVO" not in [p["nombre"] for p in op.parametros]


def test_parametros_por_ref_y_de_nivel_path(cat):
    op = _ver(cat, "cliente", "GET", "/cliente/list")
    p = next(p for p in op.parametros if p["nombre"] == "updatedSince")
    assert p["ubicacion"] == "query" and p["requerido"] is False
    assert "actualizacion" in p["descripcion"]
    codigo = next(p for p in _ver(cat, "cliente", "GET", "/cliente/{codigo}").parametros
                  if p["nombre"] == "codigo")
    assert codigo["ubicacion"] == "path" and codigo["requerido"] is True


def test_put_lista_create_if_not_exists(cat):
    put = _ver(cat, "cliente", "PUT")
    assert "createIfNotExists" in [p["nombre"] for p in put.parametros]


def test_nunca_un_parametro_sin_nombre(cat):
    for op in cat.ver("cliente"):
        assert all(p["nombre"] for p in op.parametros)


def test_no_duplica_parametro_declarado_en_los_dos_niveles():
    paths = {"/repetido/{codigo}": {
        "get": _op(["repetido"], "repetido", "r_get",
                   [{"$ref": "#/definitions/ParametroCodigo"}]),
        "parameters": [{"$ref": "#/definitions/ParametroCodigo"}]}}
    spec = {"swagger": "2.0", "definitions": SPEC["definitions"], "tags": [], "paths": paths}
    cat = Red(spec).catalogo()
    nombres = [p["nombre"] for p in cat.ver("repetido")[0].parametros]
    assert nombres.count("codigo") == 1


def test_ver_resuelve_el_vo_externo_contra_el_host_del_swagger(red, cat):
    put = _ver(cat, "cliente", "PUT")
    assert put.tiene_body and put.body_schema_ok
    assert {"Codigo", "Descripcion"} <= set(put.body_campos)
    assert put.body_requeridos == ["Codigo", "Nombre"]
    (pedido,) = red.pedidos_vo()[:1]
    assert str(pedido.url) == "https://oneteam.finneg.com" + REF_CLIENTE


def test_ver_no_vuelca_objetos_anidados(cat):
    post = _ver(cat, "cliente", "POST")
    assert "ProvinciaItems" in post.body_campos
    assert "ControlImpositivo1" not in post.body_campos
    assert "Provincia" not in post.body_campos


def test_cachea_el_vo_y_no_lo_baja_dos_veces(red, cat):
    cat.ver("cliente")
    cat.ver("cliente")
    nuevo = red.catalogo()
    nuevo.ver("cliente")
    assert len(red.pedidos_vo()) == 1


def test_si_falla_la_bajada_del_vo_degrada():
    red = Red(SPEC, VOS, falla_vo=True)
    put = _ver(red.catalogo(), "cliente", "PUT")
    assert put.tiene_body is True
    assert put.body_schema_ok is False
    assert put.body_campos == [] and put.body_requeridos == []


def test_vo_con_error_http_o_sin_properties_degrada():
    # Los viewers devuelven un placeholder de error en lugar de un schema.
    red = Red(SPEC, {"ClienteVO": {"error": "no hay schema"}})
    assert _ver(red.catalogo(), "cliente", "PUT").body_schema_ok is False
    sw.limpiar_caches()
    assert _ver(Red(SPEC, {}).catalogo(), "cliente", "PUT").body_schema_ok is False


def test_ref_interna_en_body():
    spec = {"swagger": "2.0", "tags": [], "definitions": {
        "ClienteBody": {"required": ["Codigo"], "properties": {"Codigo": {}, "Nombre": {}}}},
        "paths": {"/cliente": {"post": _op(["cliente"], "c", "c_post", [
            {"name": "body", "in": "body", "schema": {"$ref": "#/definitions/ClienteBody"}}])}}}
    post = Red(spec).catalogo().ver("cliente")[0]
    assert post.body_schema_ok and post.body_campos == ["Codigo", "Nombre"]
    assert post.body_requeridos == ["Codigo"]


def test_no_baja_schemas_de_respuesta(red, cat):
    cat.ver("cliente")
    cat.ver("reports/ACOrdenesCompraPendientes")
    assert all("nombreVO=ClienteVO" in str(r.url) for r in red.pedidos_vo())


# ------------------------------------------------------------------ campo

def test_campo_expande_un_nivel(cat):
    sub = cat.campo("cliente", "PUT", "ProvinciaItems")
    assert "ControlImpositivo1" in sub
    assert sub["Provincia"] == {"type": "string"}


def test_campo_escalar_devuelve_vacio(cat):
    assert cat.campo("cliente", "PUT", "Codigo") == {}


def test_campo_inexistente_o_metodo_sin_body_es_swaggererror(cat):
    with pytest.raises(SwaggerError, match="ProvinciaItem"):
        cat.campo("cliente", "PUT", "ProvinciaItem")
    with pytest.raises(SwaggerError):
        cat.campo("cliente", "DELETE", "ProvinciaItems")
    with pytest.raises(SwaggerError):
        cat.campo("noexiste", "PUT", "x")


def test_campo_con_ref_interna_en_items():
    vo = {"properties": {"Items": {"type": "array",
                                   "items": {"$ref": "#/definitions/Item"}}},
          "definitions": {"Item": {"properties": {"Linea": {"type": "integer"}}}}}
    red = Red(SPEC, {"ClienteVO": vo})
    assert red.catalogo().campo("cliente", "PUT", "Items") == {"Linea": {"type": "integer"}}


def test_campo_es_case_insensitive_en_metodo(cat):
    assert "ControlImpositivo1" in cat.campo("cliente", "put", "ProvinciaItems")


def test_campo_no_expone_refs_externas_con_la_key():
    ref = f"/BSA/api/swaggerApi?key={KEY}&api=cliente&nombreVO=SubVO"
    vo = {"properties": {"Items": {"type": "array", "items": {
        "properties": {"Sub": {"$ref": ref},
                       "Nota": {"description": f"ver {KEY} y {KEY}".replace(" ", "+")},
                       "Lista": {"allOf": [{"$ref": "#/definitions/Otro"}]}}}}}}
    sub = Red(SPEC, {"ClienteVO": vo}).catalogo().campo("cliente", "PUT", "Items")
    texto = str(sub)
    assert KEY not in texto and "key=" not in texto
    assert sub["Sub"] == {"$ref": "ref a SubVO"}
    assert sub["Lista"] == {"allOf": [{"$ref": "ref a Otro"}]}


def test_campo_con_ref_externa_sin_nombrevo_no_filtra():
    vo = {"properties": {"Items": {"properties": {
        "Sub": {"$ref": f"/BSA/api/swaggerApi?key={KEY}"}}}}}
    sub = Red(SPEC, {"ClienteVO": vo}).catalogo().campo("cliente", "PUT", "Items")
    assert KEY not in str(sub) and sub["Sub"] == {"$ref": "ref externa"}


# ------------------------------------------------- mayusculas / minusculas

def test_ver_sin_importar_mayusculas_devuelve_lo_mismo(cat):
    esperado = cat.ver("cliente")
    assert esperado
    assert cat.ver("CLIENTE") == esperado
    assert cat.ver("Cliente/list") == [o for o in esperado if o.path == "/cliente/list"]
    # No se cambia el casing de lo devuelto.
    assert {o.path for o in cat.ver("movimientofondos")} == {
        "/movimientoFondos", "/movimientoFondos/{codigo}"}
    assert cat.ver("reports/acordenescomprapendientes")[0].path == (
        "/reports/ACOrdenesCompraPendientes")


def test_la_coincidencia_exacta_gana_sobre_la_de_mayusculas():
    spec = {"swagger": "2.0", "tags": [], "paths": {
        "/Cliente": {"get": _op(["a"], "a", "a_get")},
        "/cliente": {"get": _op(["b"], "b", "b_get")}}}
    assert [o.path for o in Red(spec).catalogo().ver("cliente")] == ["/cliente"]


def test_campo_sin_importar_mayusculas(cat):
    assert "ControlImpositivo1" in cat.campo("CLIENTE", "put", "provinciaitems")


# ---------------------------------------------------------- sin key en nada

def test_la_key_no_aparece_en_ninguna_salida(red, cat):
    # La key va dentro de la ref del VO; las salidas no la repiten.
    for op in cat.ver("cliente"):
        assert "abc123" not in json.dumps(op.__dict__, default=str)
    assert KEY not in json.dumps([c.__dict__ for c in cat.buscar("cliente")])
    assert "abc123" not in json.dumps(cat.campo("cliente", "PUT", "ProvinciaItems"))


def test_error_http_del_swagger_redacta_antes_de_cortar():
    key = "QZW9-corte-key-7Hk2Lm5Np8Rt"
    # La key empieza 10 caracteres antes del corte del detalle (200).
    cuerpo = "z" * 190 + key + " fin"
    cat = SwaggerCatalog(
        _settings(FINNEGANS_SWAGGER_KEY=key),
        http=httpx2.Client(transport=httpx2.MockTransport(
            lambda r: httpx2.Response(500, text=cuerpo))),
    )
    with pytest.raises(SwaggerError) as e:
        cat.spec()
    for k in range(3, len(key) + 1):
        assert key[:k] not in str(e.value), k
