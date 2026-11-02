"""El script de prueba en vivo, corrido de punta a punta contra un cliente FALSO.

Nada de esto toca Finnegans: el cliente HTTP, el swagger y la documentacion son
fakes (los mismos de tests/mcp). Se prueba que el script se niegue a correr sin
las dos confirmaciones, que haga la secuencia esperada y que jamas apunte a un
codigo que no empiece con ZZ-PRUEBA-MCP.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from finnegans_core.client import FinnegansError

RAIZ = Path(__file__).resolve().parent.parent


def _cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


fakes = _cargar("_fakes_mcp_conftest", RAIZ / "tests" / "mcp" / "conftest.py")
script = _cargar("_prueba_escritura_en_vivo", RAIZ / "scripts" / "prueba_escritura_en_vivo.py")

PREFIJO = "ZZ-PRUEBA-MCP"
FLAGS = ["--si-escribir-en-produccion", "--plantilla", "P01093"]

VO_CON_ACTIVO = {
    "required": ["Codigo", "Nombre"],
    "properties": {**fakes.VO_CLIENTE["properties"], "Activo": {"type": "boolean"}},
}


def _plantilla(**extra) -> dict:
    d = {
        "Codigo": "P01093",
        "Nombre": "Cliente real",
        "Descripcion": "no tocar",
        "Activo": True,
        "ProvinciaItems": [{"Provincia": "BA", "ControlImpositivo1": "LOCAL"}],
    }
    d.update(extra)
    return d


class Finnegans:
    """Un 'Finnegans' en memoria que atiende lo que el script le pide."""

    def __init__(self, plantilla: dict, restos: tuple[str, ...] = (),
                 falla_en: str | None = None, oculta_en_lista: bool = False,
                 relleno: int = 0) -> None:
        self.relleno = relleno  # clientes de relleno para que /list sea grande
        self.oculta_en_lista = oculta_en_lista  # /list no muestra los ZZ (p. ej. inactivos)
        self.borrado = False
        self.plantilla = plantilla
        self.registros: dict[str, dict] = {}
        for c in restos:
            self.registros[c] = {"Codigo": c, "Nombre": "resto", "Activo": False}
        self.falla_en = falla_en
        self.cliente = None  # lo pone armar()

    def clientes(self) -> dict[str, dict]:
        return {self.plantilla["Codigo"]: self.plantilla, **self.registros}

    def __call__(self, metodo, path, id, params, body):
        if self.falla_en == metodo:
            raise FinnegansError(f"Error en {metodo} {path} (HTTP 500): boom")
        if metodo == "GET" and path == "cliente/list":
            filas = [{"Codigo": c, "Nombre": r.get("Nombre")} for c, r in self.clientes().items()
                     if not (self.oculta_en_lista and c.startswith(PREFIJO))]
            return filas + [{"Codigo": f"R{i:05d}", "Nombre": f"Relleno {i} " + "x" * 30}
                            for i in range(self.relleno)]
        if metodo == "GET" and path == "cliente":
            if id not in self.clientes():
                raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")
            return copy.deepcopy(self.clientes()[id])
        if metodo in ("POST", "PUT") and path == "cliente":
            codigo = body["Codigo"]
            self.registros[codigo] = dict(copy.deepcopy(body), FechaAlta="2026-01-01")
            return "OK"
        if metodo == "DELETE" and path == "cliente":
            self.borrado = True
            self.registros.pop(id, None)
            return None
        raise AssertionError(f"llamada inesperada: {metodo} {path} {id}")


def correr(tmp_path, capsys, plantilla=None, restos=(), falla_en=None, vos=None,
           argv=FLAGS, fin=None):
    """Corre main() con fakes. Devuelve (codigo, stdout, stderr, finnegans, cliente)."""
    plantilla = _plantilla() if plantilla is None else plantilla
    fin = fin or Finnegans(plantilla, restos, falla_en)
    settings = fakes.ajustes(tmp_path)
    cli = fakes.ClienteFalso(settings, fin)
    vos = {"ClienteVO": VO_CON_ACTIVO} if vos is None else vos
    sw = fakes.catalogo(settings, fakes.SPEC, vos)
    env = {
        "FINNEGANS_CLIENT_ID": settings.client_id,
        "FINNEGANS_CLIENT_SECRET": settings.client_secret,
        "FINNEGANS_SWAGGER_KEY": settings.swagger_key,
        "FINNEGANS_DOCS_CLIENT_ID": settings.docs_client_id,
        "FINNEGANS_DOCS_SECRET_KEY": settings.docs_secret_key,
        "FINNEGANS_EXPORT_DIR": settings.export_dir,
    }
    codigo = script.main(argv, env, client=cli, swagger=sw, docs=fakes.DocsFalso())
    capturado = capsys.readouterr()
    return codigo, capturado.out, capturado.err, fin, cli


def escrituras(cli):
    return [c for c in cli.llamadas if c.metodo != "GET"]


def _codigo_destino(llamada) -> str | None:
    if llamada.id is not None:
        return llamada.id
    return (llamada.body or {}).get("Codigo")


# ------------------------------------------------------------------ rechazos


@pytest.mark.parametrize("argv", [
    [],
    ["--plantilla", "P01093"],
    ["--si-escribir-en-produccion"],
    ["--si-escribir-en-produccion", "--plantilla", "  "],
])
def test_sin_las_dos_confirmaciones_no_hace_nada(tmp_path, capsys, argv):
    codigo, out, err, fin, cli = correr(tmp_path, capsys, argv=argv)
    assert codigo != 0
    assert "No se hizo nada" in err
    assert cli.llamadas == []
    assert out == ""


def test_sin_configuracion_no_hace_nada(capsys):
    codigo = script.main(FLAGS, {})
    assert codigo != 0
    assert "No se hizo nada" in capsys.readouterr().err


# ------------------------------------------------------------- camino feliz


def test_secuencia_completa_con_resto_previo(tmp_path, capsys):
    resto = f"{PREFIJO}-VIEJO"
    codigo, out, err, fin, cli = correr(tmp_path, capsys, restos=(resto,))
    assert codigo == 0, out + err
    assert "PRUEBA OK" in out

    w = escrituras(cli)
    assert [(c.metodo, c.id) for c in w] == [
        ("DELETE", resto),
        ("POST", None),
        ("PUT", PREFIJO),
        ("PUT", PREFIJO),
        ("DELETE", PREFIJO),
    ]
    post, put_base, put_body = w[1], w[2], w[3]

    # El alta lleva solo los campos requeridos de la plantilla (Codigo y Nombre), con
    # otro codigo y nombre, mas el estado inactivo.
    assert post.body == {"Codigo": PREFIJO, "Nombre": script.NOMBRE_ALTA, "Activo": False}
    # PUT con base + cambios: el registro entero con solo el Nombre cambiado.
    assert put_base.body["Nombre"] == script.NOMBRE_EDITADO
    assert put_base.body["FechaAlta"] == "2026-01-01"  # el registro entero, releido
    assert put_base.body["Activo"] is False
    # PUT con body completo.
    assert put_body.body["Nombre"] == script.NOMBRE_BODY
    assert put_body.body["Codigo"] == PREFIJO

    # La plantilla jamas se escribe ni se modifica, y no queda nada.
    assert fin.plantilla == _plantilla()
    assert fin.registros == {}
    assert "Campos cambiados" in out and "Nombre" in out


def test_sin_restos_no_borra_antes_de_crear(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(tmp_path, capsys)
    assert codigo == 0, out + err
    assert [c.metodo for c in escrituras(cli)] == ["POST", "PUT", "PUT", "DELETE"]


def test_ninguna_llamada_apunta_a_un_codigo_sin_prefijo(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, restos=(f"{PREFIJO}-A", f"{PREFIJO}-B"))
    assert codigo == 0, out + err
    for c in escrituras(cli):
        assert c.path == "cliente"
        assert _codigo_destino(c).startswith(PREFIJO), c
        if c.body is not None:
            assert c.body["Codigo"].startswith(PREFIJO)
    # La plantilla solo se lee: GET, nunca otra cosa.
    sobre_plantilla = [c for c in cli.llamadas if c.id == "P01093"]
    assert sobre_plantilla and all(c.metodo == "GET" for c in sobre_plantilla)


def test_tipo_de_estado_se_conserva(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(tmp_path, capsys,
                                        plantilla=_plantilla(Activo="S"))
    assert codigo == 0, out + err
    assert escrituras(cli)[0].body["Activo"] == "N"


def test_flag_solo_en_el_swagger(tmp_path, capsys):
    plantilla = _plantilla()
    del plantilla["Activo"]
    codigo, out, err, fin, cli = correr(tmp_path, capsys, plantilla=plantilla)
    assert codigo == 0, out + err
    assert escrituras(cli)[0].body["Activo"] is False


# ------------------------------------------------------------------- abortos


def test_aborta_sin_campo_activo_reconocible(tmp_path, capsys):
    plantilla = _plantilla()
    del plantilla["Activo"]
    # Y el swagger tampoco lo declara.
    codigo, out, err, fin, cli = correr(tmp_path, capsys, plantilla=plantilla,
                                        vos={"ClienteVO": fakes.VO_CLIENTE},
                                        restos=(f"{PREFIJO}-VIEJO",))
    assert codigo != 0
    assert "activo" in err.lower() and "no se escribió nada" in err
    assert escrituras(cli) == []  # ni siquiera borra los restos


def test_aborta_si_el_estado_de_la_plantilla_no_se_entiende(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(tmp_path, capsys,
                                        plantilla=_plantilla(Activo="QUIZAS"))
    assert codigo != 0
    assert escrituras(cli) == []


def test_aborta_si_la_plantilla_no_existe(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, argv=["--si-escribir-en-produccion", "--plantilla", "NOEXISTE"])
    assert codigo != 0
    assert escrituras(cli) == []


def test_plantilla_con_el_prefijo_se_rechaza(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, argv=["--si-escribir-en-produccion", "--plantilla", PREFIJO])
    assert codigo != 0
    assert cli.llamadas == []


def test_guarda_rechaza_codigos_ajenos_antes_de_enviar(tmp_path):
    settings = fakes.ajustes(tmp_path)
    cli = fakes.ClienteFalso(settings, Finnegans(_plantilla()))
    ws = script.Workspace()
    try:
        server = script.crear_servidor(
            settings, client=cli, swagger=fakes.catalogo(settings, fakes.SPEC),
            docs=fakes.DocsFalso(), workspace=ws)
        prueba = script.Prueba(server, ws, lambda _t: None)
        for metodo, kw in (
            ("DELETE", dict(id="P01093")),
            ("PUT", dict(id="P01093", body={"Codigo": "P01093"})),
            ("POST", dict(body={"Codigo": "P01093", "Nombre": "x"})),
            ("POST", dict(body={"Nombre": "sin codigo"})),
            ("PUT", dict(id=f"{PREFIJO}-X", body={"Codigo": "P01093"})),
            ("PUT", dict(id=f"{PREFIJO}-X", base="t", cambios={"Codigo": "P01093"})),
            ("DELETE", dict(id="zz-prueba-mcp")),  # el prefijo es exacto
        ):
            with pytest.raises(script.ErrorPrueba):
                prueba.escribir(metodo, **kw)
        assert cli.llamadas == []
    finally:
        ws.cerrar()


def test_si_falla_un_paso_borra_el_registro_y_sale_con_error(tmp_path, capsys):
    # El segundo PUT falla: el registro de prueba ya existe y hay que sacarlo.
    fin_puts = {"n": 0}

    class FallaElSegundoPut(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            if metodo == "PUT":
                fin_puts["n"] += 1
                if fin_puts["n"] == 2:
                    raise FinnegansError("Error en PUT cliente (HTTP 500): boom")
            return super().__call__(metodo, path, id, params, body)

    plantilla = _plantilla()
    fin = FallaElSegundoPut(plantilla)
    settings = fakes.ajustes(tmp_path)
    cli = fakes.ClienteFalso(settings, fin)
    sw = fakes.catalogo(settings, fakes.SPEC, {"ClienteVO": VO_CON_ACTIVO})
    env = {
        "FINNEGANS_CLIENT_ID": settings.client_id,
        "FINNEGANS_CLIENT_SECRET": settings.client_secret,
        "FINNEGANS_SWAGGER_KEY": settings.swagger_key,
        "FINNEGANS_DOCS_CLIENT_ID": settings.docs_client_id,
        "FINNEGANS_DOCS_SECRET_KEY": settings.docs_secret_key,
    }
    codigo = script.main(FLAGS, env, client=cli, swagger=sw, docs=fakes.DocsFalso())
    err = capsys.readouterr().err
    assert codigo != 0 and "PRUEBA FALLIDA" in err
    assert [c.metodo for c in escrituras(cli)] == ["POST", "PUT", "PUT", "DELETE"]
    assert fin.registros == {}
    for c in escrituras(cli):
        assert _codigo_destino(c).startswith(PREFIJO)


def test_post_rechazado_sale_con_error_y_no_sigue(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(tmp_path, capsys, falla_en="POST")
    assert codigo != 0
    assert all(c.metodo != "PUT" for c in escrituras(cli))


def test_delete_que_no_borra_se_detecta(tmp_path, capsys):
    class NoBorra(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            if metodo == "DELETE":
                return None  # dice OK pero deja el registro
            return super().__call__(metodo, path, id, params, body)

    plantilla = _plantilla()
    fin = NoBorra(plantilla)
    settings = fakes.ajustes(tmp_path)
    cli = fakes.ClienteFalso(settings, fin)
    sw = fakes.catalogo(settings, fakes.SPEC, {"ClienteVO": VO_CON_ACTIVO})
    env = {
        "FINNEGANS_CLIENT_ID": settings.client_id,
        "FINNEGANS_CLIENT_SECRET": settings.client_secret,
        "FINNEGANS_SWAGGER_KEY": settings.swagger_key,
        "FINNEGANS_DOCS_CLIENT_ID": settings.docs_client_id,
        "FINNEGANS_DOCS_SECRET_KEY": settings.docs_secret_key,
    }
    codigo = script.main(FLAGS, env, client=cli, swagger=sw, docs=fakes.DocsFalso())
    assert codigo != 0
    assert "sigue existiendo" in capsys.readouterr().err


# ------------------------------------------------- ronda de endurecimiento

VO_CON_ITEMS = {
    "required": ["Codigo", "Nombre", "ProvinciaItems"],
    "properties": {**VO_CON_ACTIVO["properties"]},
}


def _con_ids() -> dict:
    return _plantilla(
        Id=7, GUID="aaaa-bbbb", IDCliente=99, ClienteId=5,
        ProvinciaItems=[{"Id": 1, "IdFila": 2, "Provincia": "BA", "Fila_Id": 3,
                         "Sub": [{"UUID": "u", "Valor": "x"}]}],
    )


def _claves_en_profundidad(valor):
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield k
            yield from _claves_en_profundidad(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _claves_en_profundidad(v)


def test_alta_sin_ids_de_la_plantilla_a_ninguna_profundidad(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(tmp_path, capsys, plantilla=_con_ids(),
                                        vos={"ClienteVO": VO_CON_ITEMS})
    assert codigo == 0, out + err
    post = [c for c in escrituras(cli) if c.metodo == "POST"][0].body
    assert set(post) == {"Codigo", "Nombre", "Activo", "ProvinciaItems"}
    assert post["ProvinciaItems"] == [{"Provincia": "BA", "Sub": [{"Valor": "x"}]}]
    prohibidas = {"Id", "GUID", "IDCliente", "ClienteId", "IdFila", "Fila_Id", "UUID"}
    assert not prohibidas & set(_claves_en_profundidad(post))


def test_copiar_resto_tambien_saca_los_ids(tmp_path, capsys):
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, plantilla=_con_ids(),
        argv=FLAGS + ["--copiar-resto-de-la-plantilla"])
    assert codigo == 0, out + err
    post = [c for c in escrituras(cli) if c.metodo == "POST"][0].body
    assert post["Descripcion"] == "no tocar"
    assert "Id" not in post and "GUID" not in post and "IDCliente" not in post
    assert "Id" not in post["ProvinciaItems"][0]


def test_plantilla_cambiada_tras_el_alta_aborta_sin_borrar_nada(tmp_path, capsys):
    class TocaLaPlantilla(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            r = super().__call__(metodo, path, id, params, body)
            if metodo == "POST":
                self.plantilla["Nombre"] = "pisada por el alta"
            return r

    fin = TocaLaPlantilla(_plantilla())
    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=fin)
    assert codigo != 0
    assert "CAMBIÓ" in err and "Nombre" in err and "P01093" in err
    assert [(c.metodo, c.id) for c in escrituras(cli)] == [("POST", None)]
    assert "NO borro nada" in out


def test_plantilla_que_desaparece_no_dispara_borrados(tmp_path, capsys):
    class PisaLaPlantilla(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            r = super().__call__(metodo, path, id, params, body)
            if metodo == "POST":  # el alta le cambio el codigo a la plantilla
                self.plantilla = dict(self.plantilla, Codigo="OTRO-CODIGO")
            return r

    fin = PisaLaPlantilla(_plantilla())
    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=fin)
    assert codigo != 0
    assert "YA NO EXISTE" in err
    assert [c.metodo for c in escrituras(cli)] == ["POST"]  # ni siquiera el DELETE
    assert "a mano" in out


def test_alta_que_queda_activa_aborta_y_borra(tmp_path, capsys):
    class IgnoraInactivo(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            r = super().__call__(metodo, path, id, params, body)
            if metodo == "POST":
                self.registros[body["Codigo"]]["Activo"] = True
            return r

    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=IgnoraInactivo(_plantilla()))
    assert codigo != 0 and "ACTIVA" in err
    assert [(c.metodo, c.id) for c in escrituras(cli)] == [("POST", None), ("DELETE", PREFIJO)]
    assert fin.registros == {}


def test_lectura_fallida_tras_el_delete_no_se_toma_como_no_existe(tmp_path, capsys):
    class FallaLaLectura(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            if metodo == "GET" and path == "cliente" and id == PREFIJO and self.borrado:
                raise FinnegansError("Error en GET cliente (HTTP 500): boom")
            return super().__call__(metodo, path, id, params, body)

    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=FallaLaLectura(_plantilla()))
    assert codigo == 1
    assert "PRUEBA OK" not in out and "No pude confirmar" in err


def test_listado_final_fallido_no_usa_la_tabla_vieja(tmp_path, capsys):
    class FallaElListado(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            if metodo == "GET" and path == "cliente/list" and self.borrado:
                raise FinnegansError("Error en GET cliente/list (HTTP 500): boom")
            return super().__call__(metodo, path, id, params, body)

    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=FallaElListado(_plantilla()))
    assert codigo == 1
    assert "PRUEBA OK" not in out and "cliente/list" in err


def test_campo_unico_sin_el_permiso_aborta_antes_de_escribir(tmp_path, capsys):
    vo = {"required": ["Codigo", "Nombre", "Email"],
          "properties": {**VO_CON_ACTIVO["properties"], "Email": {"type": "string"}}}
    plantilla = _plantilla(Email="secreto@ejemplo.com")
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, plantilla=plantilla, vos={"ClienteVO": vo},
        restos=(f"{PREFIJO}-VIEJO",))
    assert codigo != 0
    assert "Email" in err and "secreto@ejemplo.com" not in err
    assert "--permitir-copiar-campos-unicos" in err
    assert escrituras(cli) == []

    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, plantilla=_plantilla(Email="secreto@ejemplo.com"),
        vos={"ClienteVO": vo}, argv=FLAGS + ["--permitir-copiar-campos-unicos"])
    assert codigo == 0, out + err
    assert escrituras(cli)[0].metodo == "POST"
    assert escrituras(cli)[0].body["Email"] == "secreto@ejemplo.com"


def test_resto_por_id_directo_se_borra_aunque_el_listado_no_lo_muestre(tmp_path, capsys):
    fin = Finnegans(_plantilla(), restos=(PREFIJO,), oculta_en_lista=True)
    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=fin)
    assert codigo == 0, out + err
    assert [(c.metodo, c.id) for c in escrituras(cli)] == [
        ("DELETE", PREFIJO), ("POST", None), ("PUT", PREFIJO), ("PUT", PREFIJO),
        ("DELETE", PREFIJO)]


def _prueba_suelta(tmp_path):
    settings = fakes.ajustes(tmp_path)
    cli = fakes.ClienteFalso(settings, Finnegans(_plantilla()))
    ws = script.Workspace()
    server = script.crear_servidor(
        settings, client=cli, swagger=fakes.catalogo(settings, fakes.SPEC),
        docs=fakes.DocsFalso(), workspace=ws)
    return script.Prueba(server, ws, lambda _t: None), cli, ws


def test_llamar_no_deja_pasar_escribir(tmp_path):
    prueba, cli, ws = _prueba_suelta(tmp_path)
    try:
        with pytest.raises(script.ErrorPrueba):
            prueba.llamar("escribir", metodo="DELETE", path="cliente", id="P01093")
        assert cli.llamadas == []
    finally:
        ws.cerrar()


def test_guarda_put_sin_codigo_en_el_body_falla_cerrada(tmp_path):
    prueba, cli, ws = _prueba_suelta(tmp_path)
    try:
        with pytest.raises(script.ErrorPrueba):
            prueba.escribir("PUT", id=f"{PREFIJO}-X", body={"Nombre": "sin codigo"})
        assert cli.llamadas == []
    finally:
        ws.cerrar()


def test_regex_de_identidad_y_de_unicos():
    ids = ["id", "ID", "Id", "guid", "UUID", "IdCliente", "IDCliente", "Id_Fila",
           "ClienteId", "cliente_id", "ClienteID"]
    no_ids = ["Codigo", "Nombre", "Descripcion", "Identificacion", "Activo", "Provincia"]
    assert all(script._CLAVE_IDENTIDAD.search(k) for k in ids)
    assert not any(script._CLAVE_IDENTIDAD.search(k) for k in no_ids)
    assert script.claves_unicas(
        {"CUIT": "1", "Contactos": [{"EMail": "x", "Dni": "2"}], "Nombre": "n"}
    ) == ["CUIT", "Contactos[].Dni", "Contactos[].EMail"]


# ------------------------------------------------------- ronda 2

VO_CON_NUMERO = {
    "required": ["Codigo", "Nombre", "Numero"],
    "properties": {**VO_CON_ACTIVO["properties"], "Numero": {"type": "integer"}},
}


class UpsertPorNumero(Finnegans):
    """Un POST con el mismo Numero que un cliente existente lo pisa (y le cambia el codigo)."""

    def __init__(self, *a, corta_la_respuesta=False, **kw):
        super().__init__(*a, **kw)
        self.corta_la_respuesta = corta_la_respuesta

    def __call__(self, metodo, path, id, params, body):
        if metodo == "POST" and body.get("Numero") == self.plantilla.get("Numero"):
            self.plantilla = dict(copy.deepcopy(body), FechaAlta="2026-01-01")
            if self.corta_la_respuesta:
                raise FinnegansError("No se pudo conectar a Finnegans (cliente): timed out")
            return "OK"
        return super().__call__(metodo, path, id, params, body)


@pytest.mark.parametrize("corta", [False, True])
def test_post_que_pisa_la_plantilla_no_dispara_ningun_delete(tmp_path, capsys, corta):
    fin = UpsertPorNumero(_plantilla(Numero=123), corta_la_respuesta=corta)
    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=fin,
                                        vos={"ClienteVO": VO_CON_NUMERO})
    assert codigo != 0
    assert [c.metodo for c in escrituras(cli)] == ["POST"]  # ni DELETE ni PUT
    assert "NO borro nada" in out and "P01093" in out and PREFIJO in out


def test_cleanup_no_borra_si_no_puede_releer_la_plantilla(tmp_path, capsys):
    class FallaLaLecturaDeLaPlantilla(Finnegans):
        def __call__(self, metodo, path, id, params, body):
            if metodo == "GET" and path == "cliente" and id == "P01093" and self.registros:
                raise FinnegansError("Error en GET cliente (HTTP 500): boom")
            return super().__call__(metodo, path, id, params, body)

    codigo, out, err, fin, cli = correr(tmp_path, capsys,
                                        fin=FallaLaLecturaDeLaPlantilla(_plantilla()))
    assert codigo != 0
    assert [c.metodo for c in escrituras(cli)] == ["POST"]
    assert "NO borro nada" in out


def test_sin_requeridos_no_copia_la_plantilla_en_silencio(tmp_path, capsys):
    sin_requeridos = {"required": [], "properties": VO_CON_ACTIVO["properties"]}
    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, vos={"ClienteVO": sin_requeridos},
        restos=(f"{PREFIJO}-VIEJO",))
    assert codigo != 0
    assert "--copiar-resto-de-la-plantilla" in err
    assert escrituras(cli) == []

    codigo, out, err, fin, cli = correr(
        tmp_path, capsys, vos={"ClienteVO": sin_requeridos},
        argv=FLAGS + ["--copiar-resto-de-la-plantilla"])
    assert codigo == 0, out + err
    assert escrituras(cli)[0].body["Descripcion"] == "no tocar"


def test_listado_grande_y_plantilla_enorme_pasan_el_paso_1(tmp_path, capsys):
    plantilla = _plantilla(Notas="x" * 9000)
    fin = Finnegans(plantilla, restos=(f"{PREFIJO}-VIEJO",), relleno=300)
    codigo, out, err, fin, cli = correr(tmp_path, capsys, fin=fin)
    assert codigo == 0, out[-1500:] + err
    # De verdad usaron el formato largo de leer (no el "(N filas)" corto).
    assert "No la muestro entera" in out
    assert [(c.metodo, c.id) for c in escrituras(cli)][0] == ("DELETE", f"{PREFIJO}-VIEJO")
    assert fin.plantilla == plantilla


def test_unicos_extendidos():
    for k in ("CUIL", "NroDoc", "NroDocumento", "Mail", "CorreoElectronico", "Email",
              "DNI", "CUIT"):
        assert script.claves_unicas({k: "x"}) == [k]
    assert script.claves_unicas({"Nombre": "x", "Descripcion": "y"}) == []
