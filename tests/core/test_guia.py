from importlib import resources

import pytest

from finnegans_core.guia import TEMAS, guia
from finnegans_mcp.instrucciones import INSTRUCCIONES

PROHIBIDOS = (
    "preparar_cambio",
    "ejecutar_cambio",
    "codigo de confirmacion",
    "código de confirmación",
    "codigo_confirmacion",
    "truncado",
    "consultar_finnegans",
    "buscar_api",
    "ver_api",
    ".env",
)


def test_temas_esperados():
    assert set(TEMAS) == {
        "sucursales", "iibb", "rutas", "tipos", "escrituras", "clientes", "parametros"
    }


@pytest.mark.parametrize("tema", TEMAS)
def test_cada_tema_existe_y_no_esta_vacio(tema):
    texto = guia(tema)
    assert texto.strip()
    assert texto.startswith("#")


@pytest.mark.parametrize("tema", TEMAS)
def test_cada_tema_entra_en_el_chat(tema):
    assert len(guia(tema)) <= 8000


@pytest.mark.parametrize("tema", TEMAS)
def test_los_archivos_se_empaquetan_via_importlib_resources(tema):
    recurso = resources.files("finnegans_core.guia") / f"{tema}.md"
    assert recurso.is_file()
    assert recurso.read_text(encoding="utf-8") == guia(tema)


def test_sin_argumento_lista_los_temas():
    lista = guia()
    for tema in TEMAS:
        assert f"- {tema}:" in lista


def test_tema_desconocido_da_la_lista():
    texto = guia("inexistente")
    assert "No existe el tema" in texto
    for tema in TEMAS:
        assert tema in texto


def test_tema_se_normaliza():
    assert guia("  IIBB ") == guia("iibb")


def test_instrucciones_cortas():
    assert len(INSTRUCCIONES) < 1200


def test_instrucciones_nombran_las_herramientas():
    for nombre in ("buscar_endpoint", "ver_endpoint", "leer", "consultar",
                   "exportar", "escribir", "guia"):
        assert nombre in INSTRUCCIONES


def test_no_quedan_rastros_de_limites_viejos():
    textos = [INSTRUCCIONES, *(guia(t) for t in TEMAS)]
    for texto in textos:
        bajo = texto.lower()
        for prohibido in PROHIBIDOS:
            assert prohibido not in bajo, prohibido


def test_guia_conserva_hechos_clave():
    assert "EMPRE01" in guia("sucursales")
    assert "Formas Shop" in guia("sucursales")
    assert "ControlImpositivo1" in guia("iibb")
    assert "Convenio Multilateral" in guia("iibb")
    esc = guia("escrituras")
    assert "406" in esc and "objeto completo" in esc
    assert "createIfNotExists=1" in esc
    assert "NroInscripcionIIBB" in esc
    assert "Viewer" in guia("tipos") and "EntidadVO" in guia("tipos")
    assert "updatedSince" in guia("tipos")
    assert "C02155" in guia("clientes")
    par = guia("parametros")
    assert "arbol(nombre)" in par and "DEALS" in par
    for const in (
        "getCurrentDate", "getFirstDayOfWeek", "getFirstDayOfMonth",
        "getLastDayOfMonth", "getFirstDayOfYear", "getLastDayOfYear",
        "getFirstDayOfLastMonth", "getLastDayOfLastMonth", "getFirstDayOfLastWeek",
        "getLastDayOfLastWeek", "getFirstDayOfLastYear", "getLastDayOfLastYear",
    ):
        assert const in par
