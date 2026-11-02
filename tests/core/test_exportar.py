import csv

import openpyxl

from finnegans_core.exportar import exportar

COLS = ["nombre", "monto"]
FILAS = [("José Ñandú", 10), ("Compañía Ábaco", 2.5), ("=1+1", None)]


def test_exportar_xlsx_y_csv(tmp_path):
    p = exportar(COLS, FILAS, tmp_path, "informe", "xlsx")
    assert p == tmp_path / "informe.xlsx"
    ws = openpyxl.load_workbook(p).active
    assert [c.value for c in ws[1]] == COLS
    assert ws["A2"].value == "José Ñandú"
    assert ws["A3"].value == "Compañía Ábaco"
    assert ws["A4"].value == "=1+1"  # texto, no formula
    assert ws["A4"].data_type == "s"

    p2 = exportar(COLS, FILAS, tmp_path, "informe", "xlsx")
    assert p2.name == "informe (2).xlsx"
    p3 = exportar(COLS, FILAS, tmp_path, "informe", "xlsx")
    assert p3.name == "informe (3).xlsx"

    c = exportar(COLS, FILAS, tmp_path, "informe", "csv")
    assert c.read_bytes().startswith(b"\xef\xbb\xbf")
    with open(c, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.reader(f))
    assert filas[0] == COLS
    assert filas[1][0] == "José Ñandú"
    assert filas[3] == ["=1+1", ""]
    c2 = exportar(COLS, FILAS, tmp_path, "informe", "csv")
    assert c2.name == "informe (2).csv"


def test_exportar_crea_carpeta_y_sanea_nombre(tmp_path):
    destino = tmp_path / "a" / "b"
    p = exportar(COLS, FILAS, destino, 'ventas: "2024"/Q1?', "csv")
    assert p.parent == destino
    assert not set('<>:"/\\|?*') & set(p.name)
    assert p.suffix == ".csv"


def test_exportar_nombre_con_extension_no_se_duplica(tmp_path):
    p = exportar(COLS, FILAS, tmp_path, "datos.xlsx", "xlsx")
    assert p.name == "datos.xlsx"


def test_exportar_nombre_vacio_o_reservado(tmp_path):
    assert exportar(COLS, FILAS, tmp_path, "???", "csv").stem
    assert exportar(COLS, FILAS, tmp_path, "CON", "csv").stem.upper() != "CON"


def test_exportar_valores_complejos_y_control_chars(tmp_path):
    filas = [({"a": 1, "b": "ñ"}, "ok\x00mal"), ([1, 2], None)]
    p = exportar(["x", "y"], filas, tmp_path, "raro", "xlsx")
    ws = openpyxl.load_workbook(p).active
    assert ws["A2"].value == '{"a": 1, "b": "ñ"}'
    assert ws["B2"].value == "okmal"
    c = exportar(["x", "y"], filas, tmp_path, "raro", "csv")
    with open(c, encoding="utf-8-sig", newline="") as f:
        leidas = list(csv.reader(f))
    assert leidas[1][0] == '{"a": 1, "b": "ñ"}'
    assert leidas[1][1] == "okmal"
    assert leidas[2] == ["[1, 2]", ""]
