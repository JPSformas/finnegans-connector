import os

import pytest

from finnegans_core.presupuesto import (
    RESPUESTA_MAX_CHARS,
    formatear_tabla,
    nombre_tabla,
    resumir_valor,
)
from finnegans_core.workspace import ConsultaInvalida, Resumen, Workspace


def _clientes(n: int) -> list[dict]:
    return [
        {
            "Codigo": f"P-{i:05d}",
            "RazonSocial": f"Cliente número {i} S.A.",
            "Cuit": f"30-{i:08d}-7",
            "Activo": i % 2 == 0,
        }
        for i in range(n)
    ]


@pytest.fixture
def ws():
    w = Workspace()
    yield w
    w.cerrar()


def test_cargar_lista_de_objetos(ws):
    r = ws.cargar("cliente", _clientes(4150))
    assert isinstance(r, Resumen)
    assert r.tabla == "cliente"
    assert r.filas == 4150
    assert len(r.columnas) == 4
    assert all(len(c) == 2 for c in r.columnas)
    assert len(r.muestra) < 1500
    assert "P-00000" in r.muestra


def test_cargar_objeto_unico_es_tabla_de_una_fila(ws):
    dato = {"Codigo": "X1", "Nombre": "Ñandú", "Items": [1, 2, 3]}
    r = ws.cargar("uno", dato)
    assert r.filas == 1
    assert ws.crudo("uno") == dato


def test_crudo_inexistente_da_keyerror(ws):
    with pytest.raises(KeyError):
        ws.crudo("nada")


def test_cargar_anidados_permite_unnest(ws):
    ws.cargar(
        "t",
        [{"Id": 1, "ProvinciaItems": [{"Cod": "A"}, {"Cod": "B"}]}],
    )
    out = ws.consultar("SELECT unnest(ProvinciaItems) FROM t")
    assert "de 2" in out


def test_cargar_casos_raros(ws):
    r = ws.cargar("vacia", [])
    assert r.tabla is None and r.filas == 0
    assert "vac" in r.nota.lower()

    r = ws.cargar("nums", [1, 2])
    assert r.tabla == "nums" and r.filas == 2
    assert [c[0] for c in r.columnas] == ["valor"]

    r = ws.cargar("txt", "texto")
    assert r.tabla is None and "texto" in r.nota

    r = ws.cargar("nada", None)
    assert r.tabla is None and r.nota

    largo = "x" * 2000
    r = ws.cargar("largo", largo)
    assert r.tabla is None
    assert largo[:500] in r.nota and largo[:501] not in r.nota


def test_cargar_heterogeneo_no_falla(ws):
    datos = [{"a": 1}] * 25000 + [{"a": 2, "b": "tarde"}]
    r = ws.cargar("het", datos)
    assert r.filas == 25001
    assert "b" in [c[0] for c in r.columnas]


def test_cargar_reemplaza_tabla_existente(ws):
    ws.cargar("t", [{"a": 1}])
    r = ws.cargar("t", [{"a": 1}, {"a": 2}])
    assert r.filas == 2


def test_muestra_de_tabla_ancha_se_mantiene_chica(ws):
    fila = {f"Campo{i}": "v" * 300 for i in range(40)}
    r = ws.cargar("ancha", [fila] * 5)
    assert len(r.muestra) < 1500


def test_consultar_pagina_y_dice_como_seguir(ws):
    ws.cargar("cliente", _clientes(4150))
    out = ws.consultar("SELECT * FROM cliente ORDER BY Codigo")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "de 4150" in out
    assert "desde=" in out
    n = int(out.split("desde=")[1].split(")")[0])
    assert 0 < n < 4150
    sig = ws.consultar("SELECT * FROM cliente ORDER BY Codigo", desde=n)
    assert f"P-{n:05d}" in sig
    assert f"P-{n - 1:05d}" not in sig
    fin = ws.consultar("SELECT * FROM cliente", desde=4150)
    assert "no hay más filas" in fin


def test_consultar_resultado_chico_no_ofrece_seguir(ws):
    ws.cargar("cliente", _clientes(3))
    out = ws.consultar("SELECT Codigo FROM cliente ORDER BY 1")
    assert "de 3" in out
    assert "desde=" not in out


def test_consultar_sin_filas(ws):
    ws.cargar("cliente", _clientes(3))
    out = ws.consultar("SELECT * FROM cliente WHERE Codigo = 'zzz'")
    assert "0 filas" in out


def test_consultar_no_corta_celdas(ws):
    largo = "y" * 3000
    ws.cargar("t", [{"a": largo}])
    assert largo in ws.consultar("SELECT a FROM t")


@pytest.mark.parametrize(
    "sql",
    [
        "COPY t TO 'x.csv'",
        "ATTACH 'x.db'",
        "INSTALL httpfs",
        "CREATE TABLE z AS SELECT 1",
        "SELECT 1; DROP TABLE t",
        "DROP TABLE t",
        "SET memory_limit='100GB'",
        "SELECT * FROM query('DROP TABLE t')",
        "",
    ],
)
def test_consultar_rechaza_lo_que_no_es_lectura(ws, sql):
    ws.cargar("t", [{"a": 1}])
    with pytest.raises(ConsultaInvalida):
        ws.consultar(sql)
    assert "t" in ws.consultar("SHOW TABLES")
    assert "de 1" in ws.consultar("SELECT * FROM t")


def test_consultar_no_lee_archivos_de_la_pc(ws):
    ruta = os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "win.ini")
    ruta = ruta.replace(os.sep, "/")
    with pytest.raises(ConsultaInvalida) as e:
        ws.consultar(f"SELECT * FROM read_csv('{ruta}')")
    assert "Permission" in str(e.value) or "disabled" in str(e.value)


def test_consultar_error_de_sql_es_consulta_invalida(ws):
    ws.cargar("t", [{"a": 1}])
    with pytest.raises(ConsultaInvalida) as e:
        ws.consultar("SELECT noexiste FROM t")
    assert "noexiste" in str(e.value)


def test_show_describe_y_summarize_funcionan(ws):
    ws.cargar("alfa", [{"a": 1}])
    ws.cargar("beta", [{"b": "x"}])
    out = ws.consultar("SHOW TABLES")
    assert "alfa" in out and "beta" in out
    assert "column_name" in ws.consultar("DESCRIBE alfa")
    assert "column_name" in ws.consultar("SUMMARIZE alfa")


def test_ejecutar_devuelve_columnas_y_filas(ws):
    ws.cargar("t", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
    cols, filas = ws.ejecutar("SELECT a, b FROM t ORDER BY a")
    assert cols == ["a", "b"]
    assert filas == [(1, "x"), (2, "y")]
    with pytest.raises(ConsultaInvalida):
        ws.ejecutar("DELETE FROM t")


def test_cerrar_borra_el_directorio_privado():
    w = Workspace()
    w.cargar("t", [{"a": 1}])
    d = w._dir
    assert os.path.isdir(d)
    assert os.listdir(d) == []  # el NDJSON se borra apenas se carga
    w.cerrar()
    assert not os.path.exists(d)


def test_nombre_tabla():
    assert nombre_tabla("reports/ACOrdenesCompraPendientes") == "acordenescomprapendientes"
    assert nombre_tabla("cliente", "P-01093") == "cliente_p_01093"
    assert nombre_tabla("compañía/list") == "compania"
    assert nombre_tabla("cliente/list") == "cliente"
    assert nombre_tabla("dirección") == "direccion"
    assert nombre_tabla("123") == "t_123"
    assert nombre_tabla("año") == "ano"


def test_formatear_tabla_cabe_y_no_corta_celdas():
    filas = [(i, "a" * 50) for i in range(1000)]
    txt, n = formatear_tabla(["n", "s"], filas, 2000)
    assert len(txt) <= 2000
    assert 0 < n < 1000
    assert txt.count("\n") == n + 1  # cabecera + separador + n filas
    assert "a" * 50 in txt


def test_formatear_tabla_siempre_incluye_una_fila():
    txt, n = formatear_tabla(["s"], [("z" * 500,)], 100)
    assert n == 1
    assert "z" * 500 in txt


def test_formatear_tabla_escapa_pipes_y_saltos():
    txt, _ = formatear_tabla(["s"], [("a|b\nc",)], 1000)
    assert "a\\|b c" in txt


def test_resumir_valor():
    assert resumir_valor("corto") == "corto"
    assert resumir_valor(None) == ""
    largo = resumir_valor("x" * 500)
    assert largo.endswith("…") and len(largo) <= 120
    assert resumir_valor({"a": "ñ"}) == '{"a": "ñ"}'
