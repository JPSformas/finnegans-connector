"""Workspace: DuckDB en memoria donde viven los resultados grandes de Finnegans.

Claude no recibe los datos completos: se cargan aca como tablas y se consultan
con SQL de solo lectura; al chat solo llegan paginas chicas. La conexion queda
aislada del resto de la PC: solo puede leer su directorio temporal privado, no
instala extensiones y la configuracion queda bloqueada.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import weakref
from dataclasses import dataclass
from typing import Any, Callable

import duckdb

from .presupuesto import RESPUESTA_MAX_CHARS, formatear_tabla, resumir_valor

_MUESTRA_FILAS = 3
_MUESTRA_MAX_CHARS = 1500
_NOTA_MAX_CHARS = 500
# Reserva para el encabezado/pie ("Filas 1–37 de 4150. Para seguir: ...").
_RESERVA_MENSAJE = 250
_ERROR_MAX_CHARS = 1500


class ConsultaInvalida(Exception):
    """La consulta no es de solo lectura o DuckDB la rechazo."""


@dataclass
class Resumen:
    tabla: str | None
    filas: int
    columnas: list[tuple[str, str]]
    muestra: str
    nota: str | None


def _q(nombre: str) -> str:
    """Identificador SQL entre comillas dobles."""
    return '"' + nombre.replace('"', '""') + '"'


def _ruta_sql(ruta: str) -> str:
    return ruta.replace(os.sep, "/").replace("'", "''")


class Workspace:
    def __init__(self, memoria: str = "1GB") -> None:
        self._dir = tempfile.mkdtemp(prefix="finnegans_ws_")
        self._finalizador = weakref.finalize(
            self, shutil.rmtree, self._dir, ignore_errors=True
        )
        self._crudos: dict[str, Any] = {}
        self._redactar: Callable[[str], str] = lambda texto: texto
        self._n_archivo = 0
        self._con = duckdb.connect(":memory:")
        # Orden importa: primero el directorio permitido, despues cerrar el
        # acceso externo, y recien al final bloquear la configuracion.
        self._con.execute("SET allowed_directories=[?]", [self._dir.replace(os.sep, "/")])
        # (antes de cerrar el acceso externo) Si no, DuckDB derrama a <CWD>/.tmp y lo agrega a los permitidos.
        self._con.execute(
            "SET temp_directory=?", [self._dir.replace(os.sep, "/") + "/spill"]
        )
        self._con.execute("SET enable_external_access=false")
        self._con.execute("SET autoinstall_known_extensions=false")
        self._con.execute("SET autoload_known_extensions=false")
        self._con.execute("SET memory_limit=?", [memoria])
        self._con.execute("SET lock_configuration=true")

    def usar_redactor(self, redactar: Callable[[str], str]) -> None:
        """Funcion que borra secretos de la muestra y la nota, antes de cortarlas.

        Se aplica antes del corte: un secreto partido al medio ya no se
        reconoce y su primera parte quedaria visible.
        """
        self._redactar = redactar

    def _msg(self, e: Exception) -> str:
        """Mensaje de DuckDB acotado: es util para Claude pero no debe inundar.

        Se redacta antes de cortar: DuckDB repite valores de las celdas y un
        secreto partido por el corte ya no se reconoce.
        """
        t = self._redactar(str(e))
        if len(t) > _ERROR_MAX_CHARS:
            t = t[:_ERROR_MAX_CHARS] + "… (mensaje cortado)"
        return t

    # -- ciclo de vida ----------------------------------------------------

    def cerrar(self) -> None:
        """Cierra la conexion y borra el directorio temporal privado."""
        try:
            self._con.close()
        except duckdb.Error:
            pass
        self._finalizador()

    # -- carga ------------------------------------------------------------

    def cargar(self, tabla: str, datos: Any) -> Resumen:
        """Carga `datos` (JSON ya parseado) como tabla `tabla` y la resume."""
        if isinstance(datos, dict):
            registros = [datos]
        elif isinstance(datos, list):
            if not datos:
                self._olvidar(tabla)
                return Resumen(None, 0, [], "", "La API devolvió una lista vacía (sin filas).")
            registros = [x if isinstance(x, dict) else {"valor": x} for x in datos]
        else:
            # Recargar con algo que no es tabla no debe dejar la anterior:
            # escribir(base=...) la usaría como base de un cambio.
            self._olvidar(tabla)
            texto = datos if isinstance(datos, str) else json.dumps(datos, ensure_ascii=False, default=str)
            texto = self._redactar(texto)
            nota = f"La API devolvió un valor sin forma de tabla: {texto[:_NOTA_MAX_CHARS]}"
            if len(texto) > _NOTA_MAX_CHARS:
                nota += f"… (texto cortado: tenía {len(texto)} caracteres)"
            return Resumen(None, 0, [], "", nota)

        self._n_archivo += 1
        ruta = os.path.join(self._dir, f"carga_{self._n_archivo}.ndjson")
        try:
            with open(ruta, "w", encoding="utf-8", newline="\n") as f:
                for r in registros:
                    f.write(json.dumps(r, ensure_ascii=False, default=str))
                    f.write("\n")
            try:
                self._con.execute(
                    f"CREATE OR REPLACE TABLE {_q(tabla)} AS SELECT * FROM "
                    f"read_json_auto('{_ruta_sql(ruta)}', sample_size=-1, "
                    f"maximum_object_size=33554432, "
                    f"map_inference_threshold=-1)"
                )
            except duckdb.Error as e:
                self._olvidar(tabla)
                raise ConsultaInvalida(
                    f"No se pudo cargar '{tabla}' como tabla: {self._msg(e)}"
                ) from e
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

        try:
            resumen = self._resumen(tabla)
        except duckdb.Error as e:
            self._olvidar(tabla)
            raise ConsultaInvalida(
                f"Se cargó '{tabla}' pero no se pudo resumir: {self._msg(e)}"
            ) from e
        self._crudos[tabla] = datos
        return resumen

    def _olvidar(self, tabla: str) -> None:
        """Quita la tabla y su JSON crudo (si existían)."""
        self._crudos.pop(tabla, None)
        try:
            self._con.execute(f"DROP TABLE IF EXISTS {_q(tabla)}")
        except duckdb.Error:
            pass

    def crudo(self, tabla: str) -> Any:
        """El JSON original tal como se cargó. KeyError si no existe."""
        return self._crudos[tabla]

    def _resumen(self, tabla: str) -> Resumen:
        t = _q(tabla)
        filas = self._con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        columnas = [
            (c[0], str(c[1]))
            for c in self._con.execute(f"DESCRIBE {t}").fetchall()
        ]
        muestra_filas = self._con.execute(
            f"SELECT * FROM {t} LIMIT {_MUESTRA_FILAS}"
        ).fetchall()
        return Resumen(
            tabla, filas, columnas,
            self._muestra([c[0] for c in columnas], muestra_filas), None,
        )

    def _muestra(self, nombres: list[str], filas: list[tuple]) -> str:
        """Filas de muestra acortadas hasta que entren en el tope.

        Si ni una fila entra (muchas columnas), lista los nombres de columna
        y avisa cuantas faltan: nunca recorta en silencio. Cada celda se
        redacta entera antes de cortarla.
        """
        enteras = [
            tuple(self._redactar(resumir_valor(v, 10**9)) for v in f) for f in filas
        ]
        largo = 120
        while True:
            chicas = [tuple(resumir_valor(v, largo) for v in f) for f in enteras]
            texto, _ = formatear_tabla(nombres, chicas, 10**9)
            if len(texto) <= _MUESTRA_MAX_CHARS or largo <= 8:
                break
            largo //= 2
        if len(texto) > _MUESTRA_MAX_CHARS and len(filas) > 1:
            texto, _ = formatear_tabla(nombres, chicas[:1], 10**9)
        if len(texto) <= _MUESTRA_MAX_CHARS:
            return texto
        aviso = (
            f"Tabla demasiado ancha para mostrar filas de muestra ({len(nombres)} "
            "columnas). Consultá pocas columnas con consultar(sql). Columnas: "
        )
        mostradas: list[str] = []
        usado = len(aviso)
        for nom in nombres:
            if usado + len(nom) + 2 > _MUESTRA_MAX_CHARS - 40:
                break
            mostradas.append(nom)
            usado += len(nom) + 2
        resto = len(nombres) - len(mostradas)
        return aviso + ", ".join(mostradas) + (f" … y {resto} columnas más" if resto else "")

    # -- consulta ---------------------------------------------------------

    def ejecutar(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Ejecuta una sola consulta de lectura y devuelve (columnas, filas)."""
        try:
            sentencias = duckdb.extract_statements(sql)
        except duckdb.Error as e:
            raise ConsultaInvalida(f"SQL inválido: {self._msg(e)}") from e
        if len(sentencias) != 1:
            raise ConsultaInvalida(
                "Mandá exactamente una sentencia SQL por consulta."
            )
        # SHOW, DESCRIBE, SUMMARIZE, WITH y FROM-first tambien son SELECT.
        if sentencias[0].type != duckdb.StatementType.SELECT:
            raise ConsultaInvalida(
                "Solo se permiten consultas de lectura (SELECT, WITH, SHOW, "
                "DESCRIBE, SUMMARIZE). No se puede modificar ni leer archivos."
            )
        try:
            cur = self._con.execute(sql)
            columnas = [d[0] for d in cur.description]
            return columnas, cur.fetchall()
        except duckdb.Error as e:
            raise ConsultaInvalida(f"La consulta falló: {self._msg(e)}") from e

    def consultar(self, sql: str, desde: int = 0) -> str:
        """Resultado paginado como tabla markdown que cabe en el presupuesto."""
        columnas, filas = self.ejecutar(sql)
        total = len(filas)
        desde = max(desde, 0)
        if total == 0:
            return "La consulta devolvió 0 filas."
        if desde >= total:
            return (
                f"Desde la fila {desde} no hay más filas: "
                f"la consulta devolvió {total}."
            )
        tabla, n = formatear_tabla(
            columnas, filas[desde:], RESPUESTA_MAX_CHARS - _RESERVA_MENSAJE
        )
        hasta = desde + n
        if len(tabla) > RESPUESTA_MAX_CHARS - _RESERVA_MENSAJE:
            # Ni una sola fila entra: no se manda cortada ni entera.
            return (
                f"La fila {desde + 1} es demasiado ancha: tiene {len(columnas)} "
                f"columnas y ocupa unos {len(tabla)} caracteres (el máximo por "
                f"respuesta es {RESPUESTA_MAX_CHARS}). Pedí menos columnas, "
                "acortá textos con substr(col, 1, 200), o usá exportar para "
                "guardar el resultado completo en un archivo."
            )
        encabezado = f"Filas {desde + 1}–{hasta} de {total}."
        if hasta < total:
            encabezado += f" Para seguir: consultar(sql, desde={hasta})"
        return f"{encabezado}\n\n{tabla}"
