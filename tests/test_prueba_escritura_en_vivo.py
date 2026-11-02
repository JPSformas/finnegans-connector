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
                 falla_en: str | None = None) -> None:
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
            return [{"Codigo": c, "Nombre": r.get("Nombre")} for c, r in self.clientes().items()]
        if metodo == "GET" and path == "cliente":
            if id not in self.clientes():
                raise FinnegansError(f"Error en GET cliente (HTTP 404): no existe {id}")
            return copy.deepcopy(self.clientes()[id])
        if metodo in ("POST", "PUT") and path == "cliente":
            codigo = body["Codigo"]
            self.registros[codigo] = dict(copy.deepcopy(body), FechaAlta="2026-01-01")
            return "OK"
        if metodo == "DELETE" and path == "cliente":
            self.registros.pop(id, None)
            return None
        raise AssertionError(f"llamada inesperada: {metodo} {path} {id}")


def correr(tmp_path, capsys, plantilla=None, restos=(), falla_en=None, vos=None,
           argv=FLAGS):
    """Corre main() con fakes. Devuelve (codigo, stdout, stderr, finnegans, cliente)."""
    plantilla = _plantilla() if plantilla is None else plantilla
    fin = Finnegans(plantilla, restos, falla_en)
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

    # El alta sale de la plantilla: mismos campos, otro codigo y nombre, inactiva.
    esperado = dict(_plantilla(), Codigo=PREFIJO, Nombre=script.NOMBRE_ALTA, Activo=False)
    assert post.body == esperado
    # PUT con base + cambios: el registro entero con solo el Nombre cambiado.
    assert put_base.body["Nombre"] == script.NOMBRE_EDITADO
    assert put_base.body["Descripcion"] == "no tocar"
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
