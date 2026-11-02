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
from typing import Any

import duckdb

from .presupuesto import RESPUESTA_MAX_CHARS, formatear_tabla, resumir_valor

_MUESTRA_FILAS = 3
_MUESTRA_MAX_CHARS = 1500
_NOTA_MAX_CHARS = 500
# Reserva para el encabezado/pie ("Filas 1–37 de 4150. Para seguir: ...").
_RESERVA_MENSAJE = 250


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
        self._n_archivo = 0
        self._con = duckdb.connect(":memory:")
        # Orden importa: primero el directorio permitido, despues cerrar el
        # acceso externo, y recien al final bloquear la configuracion.
        self._con.execute("SET allowed_directories=[?]", [self._dir.replace(os.sep, "/")])
        self._con.execute("SET enable_external_access=false")
        self._con.execute("SET autoinstall_known_extensions=false")
        self._con.execute("SET autoload_known_extensions=false")
        self._con.execute("SET memory_limit=?", [memoria])
        self._con.execute("SET lock_configuration=true")

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
                return Resumen(None, 0, [], "", "La API devolvió una lista vacía (sin filas).")
            registros = [x if isinstance(x, dict) else {"valor": x} for x in datos]
        else:
            texto = json.dumps(datos, ensure_ascii=False, default=str) if not isinstance(datos, str) else datos
            return Resumen(
                None, 0, [], "",
                f"La API devolvió un valor sin forma de tabla: {texto[:_NOTA_MAX_CHARS]}",
            )

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
                    f"maximum_object_size=33554432)"
                )
            except duckdb.Error as e:
                raise ConsultaInvalida(
                    f"No se pudo cargar '{tabla}' como tabla: {e}"
                ) from e
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

        self._crudos[tabla] = datos
        return self._resumen(tabla)

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

    @staticmethod
    def _muestra(nombres: list[str], filas: list[tuple]) -> str:
        """Filas de muestra acortadas hasta que entren en el tope."""
        largo = 120
        while True:
            chicas = [tuple(resumir_valor(v, largo) for v in f) for f in filas]
            texto, _ = formatear_tabla(nombres, chicas, 10**9)
            if len(texto) <= _MUESTRA_MAX_CHARS or largo <= 8:
                break
            largo //= 2
        if len(texto) > _MUESTRA_MAX_CHARS and len(filas) > 1:
            texto, _ = formatear_tabla(nombres, chicas[:1], 10**9)
        return texto

    # -- consulta ---------------------------------------------------------

    def ejecutar(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Ejecuta una sola consulta de lectura y devuelve (columnas, filas)."""
        try:
            sentencias = duckdb.extract_statements(sql)
        except duckdb.Error as e:
            raise ConsultaInvalida(f"SQL inválido: {e}") from e
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
            raise ConsultaInvalida(f"La consulta falló: {e}") from e

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
        encabezado = f"Filas {desde + 1}–{hasta} de {total}."
        if hasta < total:
            encabezado += f" Para seguir: consultar(sql, desde={hasta})"
        return f"{encabezado}\n\n{tabla}"
