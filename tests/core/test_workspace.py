import os

import pytest

from finnegans_core.presupuesto import (
    PALABRAS_RESERVADAS,
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


# --- ronda de arreglos 1 ---------------------------------------------------


def test_spill_y_directorios_permitidos_quedan_en_el_dir_privado(ws):
    base = os.path.normcase(os.path.realpath(ws._dir))

    def adentro(p: str) -> bool:
        return os.path.normcase(os.path.realpath(p)).startswith(base)

    temp = ws._con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert adentro(temp)
    permitidos = ws._con.execute(
        "SELECT unnest(current_setting('allowed_directories'))"
    ).fetchall()
    assert permitidos
    assert all(adentro(p[0]) for p in permitidos)


def test_fechas_con_zona_horaria_se_cargan_y_consultan(ws):
    r = ws.cargar("t", [{"f": "2024-01-02T10:00:00Z"}, {"f": "2024-01-02T10:00:00-03:00"}])
    assert r.filas == 2
    assert "de 2" in ws.consultar("SELECT * FROM t")


def test_error_en_el_resumen_no_deja_tabla_a_medias(ws, monkeypatch):
    def boom(self, tabla):
        raise duckdb_error()

    import duckdb

    def duckdb_error():
        return duckdb.InvalidInputException("falla simulada")

    monkeypatch.setattr(Workspace, "_resumen", boom)
    with pytest.raises(ConsultaInvalida):
        ws.cargar("t", [{"a": 1}])
    with pytest.raises(KeyError):
        ws.crudo("t")
    with pytest.raises(ConsultaInvalida):
        ws.consultar("SELECT * FROM t")


def test_consultar_fila_demasiado_ancha_da_mensaje_en_vez_de_la_fila(ws):
    ws.cargar("t", [{"a": "z" * 20000, "b": 1}])
    out = ws.consultar("SELECT * FROM t")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "z" * 100 not in out
    assert "substr" in out and "exportar" in out and "2 columnas" in out


def test_consultar_600_columnas_largas_da_mensaje(ws):
    fila = {f"columna_con_nombre_muy_largo_{i:04d}": "valor" * 10 for i in range(600)}
    r = ws.cargar("ancha", [fila])
    assert len(r.columnas) == 600  # sin inferir un MAP gigante
    assert len(r.muestra) <= 1500
    assert "columnas más" in r.muestra
    out = ws.consultar("SELECT * FROM ancha")
    assert len(out) <= RESPUESTA_MAX_CHARS
    assert "600 columnas" in out and "exportar" in out


def test_recargar_con_datos_no_tabulares_borra_tabla_y_crudo_viejos(ws):
    ws.cargar("t", [{"a": 1}])
    r = ws.cargar("t", [])
    assert r.tabla is None
    with pytest.raises(KeyError):
        ws.crudo("t")
    with pytest.raises(ConsultaInvalida):
        ws.consultar("SELECT * FROM t")
    ws.cargar("u", {"a": 1})
    ws.cargar("u", "texto suelto")
    with pytest.raises(KeyError):
        ws.crudo("u")


def test_nota_cortada_lo_dice():
    w = Workspace()
    try:
        largo = "x" * 600
        nota = w.cargar("n", largo).nota
        assert "…" in nota and "cortado" in nota and "600" in nota
        corto = w.cargar("n", "hola").nota
        assert "cortado" not in corto
    finally:
        w.cerrar()


def test_nombre_tabla_evita_palabras_reservadas_y_funciona_sin_comillas(ws):
    assert nombre_tabla("order") != "order"
    assert nombre_tabla("select/list") != "select"
    nombre = nombre_tabla("order")
    ws.cargar(nombre, [{"a": 1}])
    assert "de 1" in ws.consultar(f"SELECT * FROM {nombre}")


def test_palabras_reservadas_cubren_la_version_instalada():
    import duckdb

    filas = duckdb.connect().execute(
        "SELECT keyword_name FROM duckdb_keywords() "
        "WHERE keyword_category IN ('reserved', 'type_function')"
    ).fetchall()
    faltan = {f[0] for f in filas} - PALABRAS_RESERVADAS
    assert not faltan


def test_redactor_se_aplica_antes_de_cortar_muestra_y_nota():
    w = Workspace()
    try:
        w.usar_redactor(lambda t: t.replace("SECRETO-LARGO", "***"))
        r = w.cargar("t", [{"a": "x" * 110 + "SECRETO-LARGO"}])
        assert "SECRETO" not in r.muestra
        r = w.cargar("u", "x" * 495 + "SECRETO-LARGO" + "y" * 100)
        assert "SECRETO" not in (r.nota or "")
    finally:
        w.cerrar()


SECRETO_WS = "SECRETO-QUE-CRUZA-EL-CORTE"


def _ws_con_redactor():
    w = Workspace()
    w.usar_redactor(lambda t: t.replace(SECRETO_WS, "***"))
    return w


def test_error_de_consulta_se_redacta_antes_de_cortar():
    w = _ws_con_redactor()
    try:
        w.cargar("tc", [{"a": "x" * 1440 + SECRETO_WS}])
        with pytest.raises(ConsultaInvalida) as exc:
            w.consultar("SELECT CAST(a AS INTEGER) FROM tc")
        assert "SECRETO-Q" not in str(exc.value)
    finally:
        w.cerrar()


def test_error_de_carga_se_redacta_antes_de_cortar(monkeypatch):
    import duckdb

    def boom(self, tabla):
        raise duckdb.InvalidInputException("y" * 1490 + SECRETO_WS)

    w = _ws_con_redactor()
    try:
        monkeypatch.setattr(Workspace, "_resumen", boom)
        with pytest.raises(ConsultaInvalida) as exc:
            w.cargar("t", [{"a": 1}])
        assert "SECRETO-Q" not in str(exc.value)
    finally:
        w.cerrar()


# ---------------------------------------------- consultas que no caben en memoria


def test_consultar_10_millones_de_filas_trae_solo_la_pagina(ws):
    import time

    t0 = time.perf_counter()
    out = ws.consultar("SELECT range AS n FROM range(10000000)")
    sig = ws.consultar("SELECT range AS n FROM range(10000000) ORDER BY n DESC",
                       desde=9_999_990)
    duracion = time.perf_counter() - t0
    assert duracion < 5, duracion
    assert len(out) <= RESPUESTA_MAX_CHARS and len(sig) <= RESPUESTA_MAX_CHARS
    assert "de 10000000" in out and "desde=" in out
    assert "agregá ORDER BY para paginar de forma estable" in out
    # La ultima pagina (de un ORDER BY) respeta el orden y el desplazamiento.
    assert "Filas 9999991–10000000 de 10000000." in sig
    assert "| 9 |" in sig and "| 0 |" in sig and "| 10 |" not in sig
    assert "agregá ORDER BY" not in sig  # no hay pagina siguiente


def test_consultar_producto_cartesiano_no_se_trae_entero(ws):
    ws.cargar("t", [{"a": i} for i in range(3000)])
    out = ws.consultar("SELECT x.a, y.a AS b FROM t x, t y")  # 9 millones de filas
    assert "de 9000000" in out and len(out) <= RESPUESTA_MAX_CHARS


@pytest.mark.parametrize("sql", [
    "SELECT 1 AS a;",
    "SELECT 1 AS a -- comentario al final",
    "SELECT 1 AS a /* ) ; DROP TABLE t; -- */",
    "  FROM t  ;  ",
])
def test_el_envoltorio_respeta_punto_y_coma_y_comentarios(ws, sql):
    ws.cargar("t", [{"a": 1}])
    assert "de 1" in ws.consultar(sql)
    assert "de 1" in ws.consultar("SELECT * FROM t")


@pytest.mark.parametrize("sql", [
    "SELECT 1) AS _q; DROP TABLE t; SELECT (1",
    "SELECT * FROM t) AS _q; DROP TABLE t; --",
])
def test_el_envoltorio_no_deja_pasar_otra_sentencia(ws, sql):
    ws.cargar("t", [{"a": 1}])
    with pytest.raises(ConsultaInvalida):
        ws.consultar(sql)
    with pytest.raises(ConsultaInvalida):
        ws.ejecutar(sql)
    assert "de 1" in ws.consultar("SELECT * FROM t")


def test_ejecutar_con_tope_avisa_si_hay_mas(ws):
    cols, filas, hay_mas = ws.ejecutar_con_tope("SELECT range AS n FROM range(10)", tope=4)
    assert cols == ["n"] and filas == [(0,), (1,), (2,), (3,)] and hay_mas is True
    cols, filas, hay_mas = ws.ejecutar_con_tope("SELECT range AS n FROM range(4)", tope=4)
    assert len(filas) == 4 and hay_mas is False


def test_ejecutar_tiene_un_tope_de_un_millon(ws):
    from finnegans_core import workspace as modulo

    assert modulo.MAX_FILAS_EXPORT == 1_000_000
    _, filas, hay_mas = ws.ejecutar_con_tope("SELECT range FROM range(1000001)")
    assert len(filas) == 1_000_000 and hay_mas is True
