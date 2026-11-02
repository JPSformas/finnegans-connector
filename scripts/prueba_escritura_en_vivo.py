"""Prueba de escritura EN VIVO contra Finnegans, con registros descartables.

ATENCION: esto escribe en PRODUCCION. Crea, modifica y borra un cliente de
prueba (codigo ZZ-PRUEBA-MCP) pasando por las mismas herramientas MCP que usa
Claude. El cliente plantilla que elijas solo se LEE: de ahi salen los campos
obligatorios del alta. Nunca se escribe sobre otro codigo que no empiece con
ZZ-PRUEBA-MCP (hay una guarda interna que aborta antes de enviar).

Uso (las claves van por variables de entorno, nunca desde un archivo .env):

    uv run python scripts/prueba_escritura_en_vivo.py ^
        --si-escribir-en-produccion --plantilla CODIGO_DE_UN_CLIENTE

Pasos:
  1. Lee cliente/list y busca restos de corridas anteriores (ZZ-PRUEBA-MCP%).
  2. Lee la plantilla y decide como dejar el alta inactiva (solo lectura).
  3. Borra los restos que hubiera.
  4. POST del cliente de prueba (copia de la plantilla, inactivo).
  5. PUT con base + cambios (cambia el Nombre) y verifica el resumen.
  6. PUT con el registro completo en body.
  7. DELETE y verifica que ya no existe, ni en la lectura ni en cliente/list.

Sale con codigo distinto de cero ante cualquier resultado inesperado.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import re
import sys
from typing import Any, Callable, Mapping

from finnegans_core.config import Settings
from finnegans_core.workspace import Workspace
from finnegans_mcp.escritura import TITULO_CAMBIADOS, TITULO_PROPIOS
from finnegans_mcp.server import crear_servidor

PREFIJO = "ZZ-PRUEBA-MCP"
CODIGO_PRUEBA = PREFIJO
NOMBRE_ALTA = "ZZ PRUEBA MCP - borrar"
NOMBRE_EDITADO = "ZZ PRUEBA MCP - editado"
NOMBRE_BODY = "ZZ PRUEBA MCP - body completo"
RECURSO = "cliente"
# Tope de restos a borrar: mas que esto es raro y se aborta en vez de borrar.
MAX_RESTOS = 20

TABLA_LISTA = "zz_prueba_lista"
TABLA_PLANTILLA = "zz_prueba_plantilla"
TABLA_PRUEBA = "zz_prueba_registro"
TABLA_VERIFICACION = "zz_prueba_verificacion"

_OK_ESCRITURA = "listo, Finnegans aceptó la escritura"
_OK_DELETE = "Registro eliminado"
_AVISOS_FALLO = ("falló", "No se envió", "No sé si", "no pude releer")

_FLAGS_ACTIVO = ("activo",)
# Valor "activo" de un campo de texto -> el que lo deja inactivo.
_TEXTO_A_INACTIVO = {"s": "N", "si": "N", "sí": "N", "y": "N", "yes": "N",
                     "true": "false", "1": "0"}
_TEXTO_YA_INACTIVO = {"n", "no", "false", "0"}


class ErrorPrueba(Exception):
    """Un paso no dio lo esperado: la prueba se detiene con codigo != 0."""


# ----------------------------------------------------------------- utilidades


def _normal(codigo: Any) -> str:
    return str(codigo).strip().casefold()


def _clave(registro: Mapping[str, Any], nombre: str, defecto: str) -> str:
    """Clave real del registro que coincide con `nombre` sin importar mayusculas."""
    for k in registro:
        if str(k).lower() == nombre:
            return k
    return defecto


def _unico(registro: Any) -> dict | None:
    if isinstance(registro, list) and len(registro) == 1:
        registro = registro[0]
    return registro if isinstance(registro, dict) else None


def _partes_del_resumen(texto: str) -> tuple[str, str]:
    """(seccion 'cambiados', seccion 'por su cuenta') del resumen de escribir."""
    if TITULO_CAMBIADOS not in texto or TITULO_PROPIOS not in texto:
        raise ErrorPrueba(
            "La respuesta de escribir no trae el resumen de cambios "
            f"('{TITULO_CAMBIADOS}' / '{TITULO_PROPIOS}')."
        )
    cambiados, propios = texto.split(TITULO_PROPIOS, 1)
    return cambiados, propios


def _estado_inactivo(valor: Any) -> Any:
    """El valor que deja inactivo un registro, con el mismo tipo que el de la plantilla."""
    if valor is None or isinstance(valor, bool):
        return False
    if isinstance(valor, int):
        return 0
    if isinstance(valor, str):
        clave = valor.strip().lower()
        if clave in _TEXTO_A_INACTIVO:
            inactivo = _TEXTO_A_INACTIVO[clave]
            return inactivo.upper() if valor.strip().isupper() else inactivo.lower()
        if clave in _TEXTO_YA_INACTIVO:
            return valor
    raise ErrorPrueba(
        f"No sé cómo dejar inactivo un registro cuyo campo de estado vale {valor!r}: "
        "no se escribió nada."
    )


def campos_de_body(texto_ver_endpoint: str) -> list[str]:
    """Nombres de los campos del body, tal como los lista ver_endpoint."""
    for linea in texto_ver_endpoint.splitlines():
        m = re.match(r"\s*Body \(.*?\):\s*(.*)$", linea)
        if m:
            nombres = []
            for parte in m.group(1).split(", "):
                parte = parte.strip().rstrip("*")
                if re.fullmatch(r"[A-Za-z0-9_]+", parte):
                    nombres.append(parte)
            return nombres
    return []


def campo_activo(plantilla: Mapping[str, Any], texto_ver_endpoint: str) -> str:
    """Nombre del campo que marca activo/inactivo: de la plantilla o del swagger.

    Aborta si no hay uno reconocible: no se adivina.
    """
    for k in plantilla:
        if str(k).lower() in _FLAGS_ACTIVO:
            return k
    for k in campos_de_body(texto_ver_endpoint):
        if k.lower() in _FLAGS_ACTIVO:
            return k
    raise ErrorPrueba(
        "No pude determinar el campo que marca un cliente como activo/inactivo: no está "
        "entre los campos de la plantilla ni en el body de POST cliente según el swagger "
        "(busqué 'Activo'). Para no crear un cliente activo por error, no se escribió nada."
    )


def armar_alta(plantilla: dict, flag: str) -> dict:
    """Copia cruda de la plantilla con el codigo y el nombre de prueba, inactiva."""
    body = copy.deepcopy(plantilla)
    body[_clave(body, "codigo", "Codigo")] = CODIGO_PRUEBA
    body[_clave(body, "nombre", "Nombre")] = NOMBRE_ALTA
    body[flag] = _estado_inactivo(plantilla.get(flag))
    return body


# --------------------------------------------------------------------- prueba


class Prueba:
    """Un recorrido completo contra un servidor MCP ya armado."""

    def __init__(self, server: Any, workspace: Workspace,
                 salida: Callable[[str], None] = print) -> None:
        self.server = server
        self.workspace = workspace
        self.salida = salida
        self.paso = 0
        self.pendiente_de_borrar = False

    # -- entrada/salida ----------------------------------------------------

    def titulo(self, texto: str) -> None:
        self.paso += 1
        self.salida(f"\n=== Paso {self.paso}: {texto} ===")

    def llamar(self, herramienta: str, **argumentos: Any) -> str:
        """Llama una herramienta por el registro del servidor y muestra su salida."""
        argumentos = {k: v for k, v in argumentos.items() if v is not None}
        self.salida(f"--> {herramienta}({_resumen_args(argumentos)})")
        r = asyncio.run(self.server.call_tool(herramienta, argumentos))
        texto = "".join(c.text for c in r.content)
        self.salida(texto)
        if r.is_error:
            raise ErrorPrueba(f"La herramienta {herramienta} devolvió un error.")
        return texto

    def escribir(self, metodo: str, *, id: str | None = None, body: dict | None = None,
                 base: str | None = None, cambios: dict | None = None) -> str:
        """escribir sobre cliente, con la guarda: solo codigos ZZ-PRUEBA-MCP."""
        objetivo = id
        if metodo == "POST":
            if id is not None or not isinstance(body, dict):
                raise ErrorPrueba("Guarda: un POST va con body y sin id.")
            objetivo = body.get(_clave(body, "codigo", "Codigo"))
        if not isinstance(objetivo, str) or not objetivo.startswith(PREFIJO):
            raise ErrorPrueba(
                f"Guarda: me negué a hacer {metodo} sobre el código {objetivo!r}: solo se "
                f"escribe sobre códigos que empiezan con {PREFIJO}. No se envió nada."
            )
        if isinstance(body, dict):
            cod_body = body.get(_clave(body, "codigo", "Codigo"))
            if cod_body is not None and not str(cod_body).startswith(PREFIJO):
                raise ErrorPrueba(
                    f"Guarda: el body trae el código {cod_body!r}, que no empieza con "
                    f"{PREFIJO}. No se envió nada."
                )
        if cambios and any(str(k).lower() == "codigo" for k in cambios):
            raise ErrorPrueba("Guarda: los cambios no pueden tocar el código. No se envió nada.")
        texto = self.llamar("escribir", metodo=metodo, path=RECURSO, id=id, body=body,
                            base=base, cambios=cambios)
        if any(a in texto for a in _AVISOS_FALLO):
            raise ErrorPrueba(f"escribir {metodo} {objetivo} no terminó bien (ver arriba).")
        ok = _OK_DELETE if metodo == "DELETE" else _OK_ESCRITURA
        if ok not in texto:
            raise ErrorPrueba(f"escribir {metodo} {objetivo}: no vi la confirmación '{ok}'.")
        return texto

    # -- pasos ----------------------------------------------------------------

    def restos(self) -> list[str]:
        """Codigos ZZ-PRUEBA-MCP que hay hoy en cliente/list (solo lectura)."""
        self.llamar("leer", path=f"{RECURSO}/list", tabla=TABLA_LISTA)
        sql = (f"SELECT Codigo FROM {TABLA_LISTA} "
               f"WHERE Codigo LIKE '{PREFIJO}%' ORDER BY Codigo")
        self.llamar("consultar", sql=sql)
        try:
            _, filas = self.workspace.ejecutar(sql)
        except Exception as e:  # noqa: BLE001
            raise ErrorPrueba(f"No pude buscar restos en cliente/list: {e}") from e
        codigos = [str(f[0]) for f in filas]
        raros = [c for c in codigos if not c.startswith(PREFIJO)]
        if raros:
            raise ErrorPrueba(f"La búsqueda de restos devolvió códigos ajenos: {raros[:5]}")
        if len(codigos) > MAX_RESTOS:
            raise ErrorPrueba(
                f"Hay {len(codigos)} registros {PREFIJO}* (más de {MAX_RESTOS}): es raro, "
                "revisalos a mano antes de borrar nada."
            )
        return codigos

    def leer_plantilla(self, codigo: str) -> dict:
        texto = self.llamar("leer", path=RECURSO, id=codigo, tabla=TABLA_PLANTILLA)
        if f"tabla {TABLA_PLANTILLA} (1 fila" not in texto:
            raise ErrorPrueba(f"No pude leer la plantilla '{codigo}' como un solo registro.")
        registro = _unico(self.workspace.crudo(TABLA_PLANTILLA))
        if registro is None:
            raise ErrorPrueba(f"La plantilla '{codigo}' no es un registro (objeto JSON).")
        cod = registro.get(_clave(registro, "codigo", "Codigo"))
        if cod is None or _normal(cod) != _normal(codigo):
            raise ErrorPrueba(
                f"La lectura de la plantilla '{codigo}' devolvió el código {cod!r}."
            )
        return registro

    def leer_prueba(self) -> dict:
        texto = self.llamar("leer", path=RECURSO, id=CODIGO_PRUEBA, tabla=TABLA_PRUEBA)
        if f"tabla {TABLA_PRUEBA} (1 fila" not in texto:
            raise ErrorPrueba(f"No pude leer {CODIGO_PRUEBA} después de escribirlo.")
        registro = _unico(self.workspace.crudo(TABLA_PRUEBA))
        if registro is None:
            raise ErrorPrueba(f"{CODIGO_PRUEBA} no se leyó como un registro.")
        return registro

    def correr(self, plantilla: str) -> None:
        if plantilla.startswith(PREFIJO):
            raise ErrorPrueba(f"La plantilla no puede ser un {PREFIJO}*: elegí un cliente real.")
        try:
            self._correr(plantilla)
        except BaseException:
            self._limpiar_tras_fallo()
            raise

    def _correr(self, plantilla: str) -> None:
        # Primero todo lo que solo lee: si algo no cierra, no se escribio nada.
        self.titulo("Buscar restos de corridas anteriores en cliente/list")
        restos = self.restos()
        self.salida(f"Restos encontrados: {restos or 'ninguno'}")

        self.titulo(f"Leer la plantilla '{plantilla}' (solo lectura) y ver el alta de cliente")
        molde = self.leer_plantilla(plantilla)
        ver = self.llamar("ver_endpoint", path=RECURSO, metodo="POST")
        flag = campo_activo(molde, ver)
        alta = armar_alta(molde, flag)
        self.salida(f"Campo de estado: {flag} = {alta[flag]!r} (plantilla: {molde.get(flag)!r})")
        clave_nombre = _clave(alta, "nombre", "Nombre")

        if restos:
            self.titulo("Borrar restos")
            for codigo in restos:
                self.escribir("DELETE", id=codigo)

        self.titulo(f"Alta (POST) de {CODIGO_PRUEBA}, inactivo")
        self.pendiente_de_borrar = True
        self.escribir("POST", body=alta)

        self.titulo("Editar con PUT base + cambios")
        self.leer_prueba()
        texto = self.escribir("PUT", id=CODIGO_PRUEBA, base=TABLA_PRUEBA,
                              cambios={clave_nombre: NOMBRE_EDITADO})
        cambiados, _ = _partes_del_resumen(texto)
        if clave_nombre not in cambiados or NOMBRE_EDITADO not in cambiados:
            raise ErrorPrueba(
                f"El resumen no muestra el cambio de {clave_nombre} a '{NOMBRE_EDITADO}'."
            )

        self.titulo("Editar con PUT y el registro completo en body")
        actual = self.leer_prueba()
        if actual.get(clave_nombre) != NOMBRE_EDITADO:
            raise ErrorPrueba(
                f"Tras el PUT con base el nombre quedó {actual.get(clave_nombre)!r}, "
                f"se esperaba {NOMBRE_EDITADO!r}."
            )
        body = copy.deepcopy(actual)
        body[clave_nombre] = NOMBRE_BODY
        texto = self.escribir("PUT", id=CODIGO_PRUEBA, body=body)
        _partes_del_resumen(texto)  # sin base no hay 'antes': se verifica releyendo
        registro = self.leer_prueba()
        if registro.get(clave_nombre) != NOMBRE_BODY:
            raise ErrorPrueba(
                f"Tras el PUT con body el nombre quedó {registro.get(clave_nombre)!r}, "
                f"se esperaba {NOMBRE_BODY!r}."
            )

        self.titulo(f"Baja (DELETE) de {CODIGO_PRUEBA} y verificación")
        self.escribir("DELETE", id=CODIGO_PRUEBA)
        self.pendiente_de_borrar = False
        self.llamar("leer", path=RECURSO, id=CODIGO_PRUEBA, tabla=TABLA_VERIFICACION)
        if self._existe_en_workspace(TABLA_VERIFICACION):
            raise ErrorPrueba(f"{CODIGO_PRUEBA} sigue existiendo después del DELETE.")

        self.titulo("Verificar que no quedó nada en cliente/list")
        quedan = self.restos()
        if quedan:
            raise ErrorPrueba(f"Quedaron registros en cliente/list: {quedan}")
        self.salida(f"\nTodo en orden: no queda ningún {PREFIJO}* en cliente/list.")

    def _existe_en_workspace(self, tabla: str) -> bool:
        try:
            registro = _unico(self.workspace.crudo(tabla))
        except KeyError:
            return False
        if registro is None:
            return False
        cod = registro.get(_clave(registro, "codigo", "Codigo"))
        return cod is not None and _normal(cod) == _normal(CODIGO_PRUEBA)

    def _limpiar_tras_fallo(self) -> None:
        """Si la prueba se corto con el registro creado, intenta borrarlo."""
        if not self.pendiente_de_borrar:
            return
        self.salida(f"\n--- La prueba se cortó: intento borrar {CODIGO_PRUEBA} ---")
        try:
            self.escribir("DELETE", id=CODIGO_PRUEBA)
            self.pendiente_de_borrar = False
        except Exception as e:  # noqa: BLE001
            self.salida(
                f"No pude borrar {CODIGO_PRUEBA} ({e}). Revisalo y borralo a mano en "
                "Finnegans (es un cliente inactivo de prueba)."
            )


def _resumen_args(argumentos: Mapping[str, Any]) -> str:
    partes = []
    for k, v in argumentos.items():
        txt = repr(v)
        partes.append(f"{k}={txt if len(txt) <= 60 else txt[:57] + '...'}")
    return ", ".join(partes)


# ----------------------------------------------------------------------- main


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Prueba de escritura en vivo con registros descartables (ZZ-PRUEBA-MCP). "
            "ESCRIBE EN PRODUCCIÓN."
        ),
        add_help=True,
    )
    p.add_argument("--si-escribir-en-produccion", action="store_true",
                   help="confirmación obligatoria: esta prueba escribe en producción")
    p.add_argument("--plantilla", metavar="CODIGO",
                   help="código de un cliente existente, que solo se lee, del que se "
                        "copian los campos obligatorios")
    return p


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, *,
         client: Any = None, swagger: Any = None, docs: Any = None,
         salida: Callable[[str], None] = print) -> int:
    args = _parser().parse_args(argv)
    faltan = []
    if not args.si_escribir_en_produccion:
        faltan.append("--si-escribir-en-produccion")
    if not args.plantilla or not args.plantilla.strip():
        faltan.append("--plantilla CODIGO")
    if faltan:
        print(
            "Esta prueba ESCRIBE en Finnegans de producción (crea, modifica y borra un "
            f"cliente {PREFIJO}). No se hizo nada: faltan {' y '.join(faltan)}.\n"
            "Ejemplo: uv run python scripts/prueba_escritura_en_vivo.py "
            "--si-escribir-en-produccion --plantilla CODIGO_DE_UN_CLIENTE",
            file=sys.stderr,
        )
        return 2

    settings = Settings.from_env() if env is None else Settings.from_env(env)
    sin_cargar = settings.faltantes()
    if sin_cargar:
        print(
            "Faltan variables de entorno de la configuración: "
            + ", ".join(sin_cargar)
            + ". Cargalas en la terminal (FINNEGANS_CLIENT_ID, FINNEGANS_CLIENT_SECRET, "
            "FINNEGANS_SWAGGER_KEY, FINNEGANS_DOCS_CLIENT_ID, FINNEGANS_DOCS_SECRET_KEY). "
            "No se hizo nada.",
            file=sys.stderr,
        )
        return 2

    plantilla = args.plantilla.strip()
    workspace = Workspace()
    try:
        server = crear_servidor(settings, client=client, swagger=swagger, docs=docs,
                                workspace=workspace)
        salida(
            f"PRUEBA DE ESCRITURA EN PRODUCCIÓN. Plantilla (solo lectura): {plantilla}. "
            f"Solo se escribe sobre códigos {PREFIJO}*."
        )
        Prueba(server, workspace, salida).correr(plantilla)
    except ErrorPrueba as e:
        print(f"\nPRUEBA FALLIDA: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nPRUEBA FALLIDA por un error inesperado ({type(e).__name__}): {e}",
              file=sys.stderr)
        return 1
    finally:
        workspace.cerrar()
    salida("\nPRUEBA OK: todos los pasos dieron lo esperado.")
    return 0


if __name__ == "__main__":
    # La consola de Windows no siempre es UTF-8: que los acentos no salgan rotos.
    for _flujo in (sys.stdout, sys.stderr):
        if hasattr(_flujo, "reconfigure"):
            _flujo.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
