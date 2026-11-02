"""armar_body y diff: el merge de base + cambios y el resumen despues de escribir."""
import copy

import pytest

from finnegans_mcp.escritura import armar_body, diff

BASE = {
    "Codigo": "P01093",
    "Nombre": "Viejo",
    "ProvinciaItems": [{"Provincia": "BA", "ControlImpositivo1": "LOCAL"}],
    "Activo": True,
}


def test_body_solo_se_manda_tal_cual():
    body = {"Codigo": "X", "Nombre": "Y"}
    assert armar_body(body, None, None) == body


def test_base_mas_cambios_reemplaza_solo_esas_claves():
    out = armar_body(None, BASE, {"Nombre": "Nuevo"})
    assert out == dict(BASE, Nombre="Nuevo")


def test_merge_es_superficial_reemplaza_el_valor_entero():
    nuevo = [{"Provincia": "CBA", "ControlImpositivo1": "CM"}]
    out = armar_body(None, BASE, {"ProvinciaItems": nuevo})
    assert out["ProvinciaItems"] == nuevo


def test_no_modifica_la_base():
    base = copy.deepcopy(BASE)
    out = armar_body(None, base, {"Nombre": "Nuevo"})
    out["ProvinciaItems"].append({"Provincia": "X"})
    assert base == BASE


def test_cambios_pueden_agregar_claves_nuevas():
    out = armar_body(None, BASE, {"Extra": 1})
    assert out["Extra"] == 1 and out["Nombre"] == "Viejo"


def test_body_y_base_juntos_es_error():
    with pytest.raises(ValueError):
        armar_body({"Codigo": "X"}, BASE, {"Nombre": "Y"})


def test_base_sin_cambios_es_error():
    with pytest.raises(ValueError):
        armar_body(None, BASE, None)
    with pytest.raises(ValueError):
        armar_body(None, BASE, {})


def test_cambios_sin_base_es_error():
    with pytest.raises(ValueError):
        armar_body({"Codigo": "X"}, None, {"Nombre": "Y"})


def test_nada_da_body_vacio():
    assert armar_body(None, None, None) == {}


def _partes(texto):
    marca = "Campos que la API cambió por su cuenta"
    assert "Campos cambiados" in texto and marca in texto
    return texto.split(marca, 1)


def test_diff_campos_cambiados_y_por_su_cuenta():
    enviado = dict(BASE, Nombre="Nuevo")
    despues = dict(enviado, NroInscripcionIIBB="20123456789")
    cambiados, propios = _partes(diff(BASE, enviado, despues))
    assert "Nombre" in cambiados and "Viejo" in cambiados and "Nuevo" in cambiados
    assert "→" in cambiados
    assert "NroInscripcionIIBB" in propios and "20123456789" in propios
    assert "Nombre" not in propios
    assert "Activo" not in cambiados


def test_diff_api_que_pisa_un_valor_enviado():
    enviado = dict(BASE, Nombre="Nuevo")
    despues = dict(BASE, Nombre="NUEVO")
    _, propios = _partes(diff(BASE, enviado, despues))
    assert "Nombre" in propios and "NUEVO" in propios


def test_diff_sin_cambios_lo_dice():
    texto = diff(BASE, BASE, BASE)
    cambiados, propios = _partes(texto)
    assert "ninguno" in cambiados.lower()
    assert "ninguno" in propios.lower()


def test_diff_corta_valores_largos_a_80():
    enviado = dict(BASE, Nombre="x" * 500)
    texto = diff(BASE, enviado, enviado)
    assert "x" * 81 not in texto
    assert "x" * 70 in texto
    assert "…" in texto


def test_diff_sin_antes_lo_explica():
    enviado = {"Codigo": "N"}
    despues = {"Codigo": "N", "Activo": False, "Vacio": None, "Lista": []}
    cambiados, propios = _partes(diff(None, enviado, despues))
    assert "estado previo" in cambiados
    assert "Activo" in propios
    # Lo que la API devuelve vacio y no se mando no es un cambio.
    assert "Vacio" not in propios and "Lista" not in propios


def test_diff_campo_borrado_por_la_api():
    enviado = dict(BASE)
    despues = {k: v for k, v in BASE.items() if k != "Activo"}
    _, propios = _partes(diff(BASE, enviado, despues))
    assert "Activo" in propios
