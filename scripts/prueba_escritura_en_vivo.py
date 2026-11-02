"""Prueba de escritura EN VIVO contra Finnegans, con registros descartables.

ATENCION: esto escribe en PRODUCCION. Crea, modifica y borra un cliente de
prueba (codigo ZZ-PRUEBA-MCP) pasando por las mismas herramientas MCP que usa
Claude. El cliente plantilla que elijas solo se LEE: de ahi salen los campos
obligatorios del alta. Nunca se escribe sobre otro codigo que no empiece con
ZZ-PRUEBA-MCP (hay una guarda interna que aborta antes de enviar).

Elegi una plantilla de BAJO VALOR: un cliente real pero sin importancia (el
script no la modifica, pero la lee y copia de ahi los campos obligatorios).

Uso (las claves van por variables de entorno, nunca desde un archivo .env):

    uv run python scripts/prueba_escritura_en_vivo.py ^
        --si-escribir-en-produccion --plantilla CODIGO_DE_UN_CLIENTE

Pasos:
  1. Lee cliente/list y cliente/ZZ-PRUEBA-MCP por id: busca restos de corridas
     anteriores.
  2. Lee la plantilla (y guarda una foto), arma el alta con SOLO los campos
     obligatorios del swagger (sin ids ni guids, a ninguna profundidad) y decide
     como dejarla inactiva. Si hay campos "unicos" (CUIT, documento, email...)
     aborta salvo que pases --permitir-copiar-campos-unicos.
  3. Borra los restos que hubiera.
  4. POST del cliente de prueba. Luego lo relee y verifica codigo e inactivo, y
     que la plantilla quedo identica a su foto.
  5. PUT con base + cambios (cambia el Nombre) y verifica el resumen.
  6. PUT con el registro completo en body.
  7. DELETE y verifica que la API dice que ya no existe, que no queda nada en
     cliente/list y que la plantilla sigue igual.

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

# Cada lectura usa una tabla nueva (zz_prueba_<base>_<n>): una lectura fallida no
# reemplaza la tabla, y si se reusara el nombre se verian datos viejos.
TABLA_LISTA = "zz_prueba_lista"
TABLA_PLANTILLA = "zz_prueba_plantilla"
TABLA_PRUEBA = "zz_prueba_registro"
TABLA_VERIFICACION = "zz_prueba_verificacion"

# Claves que identifican un registro: si viajaran en el alta, Finnegans podria
# modificar la plantilla en vez de crear uno nuevo.
_CLAVE_IDENTIDAD = re.compile(r"^(?i:id|guid|uuid)$|^(?i:id)[A-Z_]|(?i:_?id)$")
# Campos que suelen ser unicos en Finnegans (un duplicado rechaza el alta).
_CLAVE_UNICA = re.compile(r"cuit|documento|email|nroinscripcion|dni", re.IGNORECASE)
_INACTIVOS = {"n", "no", "false", "0"}

_NO_EXISTE = "No existe '"
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


def _lista_de_body(texto_ver_endpoint: str, solo_requeridos: bool) -> list[str]:
    for linea in texto_ver_endpoint.splitlines():
        m = re.match(r"\s*Body \(.*?\):\s*(.*)$", linea)
        if m:
            nombres = []
            for parte in m.group(1).split(", "):
                parte = parte.strip()
                requerido = parte.endswith("*")
                parte = parte.rstrip("*")
                if re.fullmatch(r"[A-Za-z0-9_]+", parte) and (requerido or not solo_requeridos):
                    nombres.append(parte)
            return nombres
    return []


def campos_de_body(texto_ver_endpoint: str) -> list[str]:
    """Nombres de los campos del body, tal como los lista ver_endpoint."""
    return _lista_de_body(texto_ver_endpoint, False)


def campos_requeridos(texto_ver_endpoint: str) -> list[str]:
    """Campos del body marcados con * (requeridos) en ver_endpoint."""
    return _lista_de_body(texto_ver_endpoint, True)


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


def _sin_identidad(valor: Any, sacadas: set[str]) -> Any:
    """Copia sin las claves de identidad (id, guid, IdXxx, XxxId...) a toda profundidad."""
    if isinstance(valor, dict):
        limpio = {}
        for k, v in valor.items():
            if _CLAVE_IDENTIDAD.search(str(k)):
                sacadas.add(str(k))
            else:
                limpio[k] = _sin_identidad(v, sacadas)
        return limpio
    if isinstance(valor, list):
        return [_sin_identidad(v, sacadas) for v in valor]
    return valor


def claves_unicas(valor: Any, ruta: str = "") -> list[str]:
    """Rutas de clave (sin valores) que parecen campos unicos, a toda profundidad."""
    encontradas: list[str] = []
    if isinstance(valor, dict):
        for k, v in valor.items():
            aqui = f"{ruta}.{k}" if ruta else str(k)
            if _CLAVE_UNICA.search(str(k)):
                encontradas.append(aqui)
            encontradas += claves_unicas(v, aqui)
    elif isinstance(valor, list):
        for v in valor:
            encontradas += claves_unicas(v, ruta + "[]")
    return sorted(set(encontradas))


def armar_alta(plantilla: dict, flag: str, requeridos: list[str] | None = None,
               copiar_resto: bool = False) -> tuple[dict, list[str]]:
    """Body del alta: solo los campos requeridos del swagger tomados de la plantilla.

    Sin lista de requeridos, o con copiar_resto, se parte de toda la plantilla. En
    todos los casos se sacan las claves de identidad a cualquier profundidad y
    despues se pisan codigo, nombre y estado (inactivo). Devuelve (body, claves
    de identidad sacadas).
    """
    if copiar_resto or not requeridos:
        origen = plantilla
    else:
        pedidos = {r.lower() for r in requeridos}
        origen = {k: v for k, v in plantilla.items() if str(k).lower() in pedidos}
    sacadas: set[str] = set()
    body = _sin_identidad(copy.deepcopy(origen), sacadas)
    body[_clave(plantilla, "codigo", "Codigo")] = CODIGO_PRUEBA
    body[_clave(plantilla, "nombre", "Nombre")] = NOMBRE_ALTA
    body[flag] = _estado_inactivo(plantilla.get(flag))
    return body, sorted(sacadas)


def _esta_inactivo(registro: Mapping[str, Any], flag: str) -> bool:
    valor = registro.get(_clave(registro, flag.lower(), flag), "<falta>")
    if valor is False or (isinstance(valor, int) and not isinstance(valor, bool) and valor == 0):
        return True
    return isinstance(valor, str) and valor.strip().lower() in _INACTIVOS


def _claves_distintas(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    return sorted(str(k) for k in set(a) | set(b) if a.get(k, "<falta>") != b.get(k, "<falta>"))


# --------------------------------------------------------------------- prueba


class Prueba:
    """Un recorrido completo contra un servidor MCP ya armado."""

    def __init__(self, server: Any, workspace: Workspace,
                 salida: Callable[[str], None] = print, *,
                 permitir_campos_unicos: bool = False,
                 copiar_resto: bool = False) -> None:
        self.server = server
        self.workspace = workspace
        self.salida = salida
        self.permitir_campos_unicos = permitir_campos_unicos
        self.copiar_resto = copiar_resto
        self.paso = 0
        self.n_tabla = 0
        self.pendiente_de_borrar = False
        # Si la plantilla pudo haber sido tocada por el alta, ZZ-PRUEBA-MCP podria ser
        # la propia plantilla: en ese caso NO se borra nada automaticamente.
        self.no_borrar = False
        self.plantilla: str | None = None
        self.tabla_prueba = ""

    # -- entrada/salida ----------------------------------------------------

    def titulo(self, texto: str) -> None:
        self.paso += 1
        self.salida(f"\n=== Paso {self.paso}: {texto} ===")

    def _tabla_nueva(self, base: str) -> str:
        self.n_tabla += 1
        return f"{base}_{self.n_tabla}"

    def _invocar(self, herramienta: str, **argumentos: Any) -> str:
        argumentos = {k: v for k, v in argumentos.items() if v is not None}
        self.salida(f"--> {herramienta}({_resumen_args(argumentos)})")
        r = asyncio.run(self.server.call_tool(herramienta, argumentos))
        texto = "".join(c.text for c in r.content)
        self.salida(texto)
        if r.is_error:
            raise ErrorPrueba(f"La herramienta {herramienta} devolvió un error.")
        return texto

    def llamar(self, herramienta: str, **argumentos: Any) -> str:
        """Llama una herramienta de LECTURA por el registro del servidor.

        `escribir` no se puede llamar por aca: solo por `self.escribir`, que tiene la guarda.
        """
        if herramienta == "escribir":
            raise ErrorPrueba("Guarda: escribir solo se llama por Prueba.escribir.")
        return self._invocar(herramienta, **argumentos)

    def _registro_a_escribir(self, body: dict | None, base: str | None) -> dict | None:
        if isinstance(body, dict):
            return body
        if base is not None:
            try:
                return _unico(self.workspace.crudo(base))
            except KeyError:
                return None
        return None

    def escribir(self, metodo: str, *, id: str | None = None, body: dict | None = None,
                 base: str | None = None, cambios: dict | None = None) -> str:
        """escribir sobre cliente, con la guarda: solo codigos ZZ-PRUEBA-MCP (falla cerrada)."""
        if metodo not in ("POST", "PUT", "DELETE"):
            raise ErrorPrueba(f"Guarda: el método {metodo} no se usa en esta prueba.")
        if metodo == "POST" and id is not None:
            raise ErrorPrueba("Guarda: un POST va con body y sin id.")
        if metodo == "DELETE" and (body is not None or base is not None or cambios):
            raise ErrorPrueba("Guarda: un DELETE va solo con id.")
        registro = None
        if metodo != "DELETE":
            # El codigo que se va a mandar (body, o la base) tiene que estar y ser de prueba.
            registro = self._registro_a_escribir(body, base)
            if registro is None:
                raise ErrorPrueba(
                    f"Guarda: no hay un registro (body o base) para {metodo}: no se envió nada."
                )
            cod_body = registro.get(_clave(registro, "codigo", "Codigo"))
            if not isinstance(cod_body, str) or not cod_body.startswith(PREFIJO):
                raise ErrorPrueba(
                    f"Guarda: el registro a enviar trae el código {cod_body!r}, que no "
                    f"empieza con {PREFIJO} (o falta). No se envió nada."
                )
        objetivo = id if metodo != "POST" else registro.get(_clave(registro, "codigo", "Codigo"))
        if not isinstance(objetivo, str) or not objetivo.startswith(PREFIJO):
            raise ErrorPrueba(
                f"Guarda: me negué a hacer {metodo} sobre el código {objetivo!r}: solo se "
                f"escribe sobre códigos que empiezan con {PREFIJO}. No se envió nada."
            )
        if cambios and any(str(k).lower() == "codigo" for k in cambios):
            raise ErrorPrueba("Guarda: los cambios no pueden tocar el código. No se envió nada.")
        texto = self._invocar("escribir", metodo=metodo, path=RECURSO, id=id, body=body,
                              base=base, cambios=cambios)
        if any(a in texto for a in _AVISOS_FALLO):
            raise ErrorPrueba(f"escribir {metodo} {objetivo} no terminó bien (ver arriba).")
        ok = _OK_DELETE if metodo == "DELETE" else _OK_ESCRITURA
        if ok not in texto:
            raise ErrorPrueba(f"escribir {metodo} {objetivo}: no vi la confirmación '{ok}'.")
        return texto

    # -- lecturas verificadas -----------------------------------------------

    def leer_registro(self, codigo: str, base_tabla: str, *,
                      puede_no_existir: bool = False) -> tuple[dict | None, str]:
        """(registro, tabla). Exige que la lectura confirme una carga o el aviso de 'No existe'.

        Cualquier otra cosa (un error, un timeout, una lista vacia) es un fallo: no se
        interpreta como 'no existe'. Con puede_no_existir devuelve (None, tabla) ante
        el aviso de que no existe.
        """
        tabla = self._tabla_nueva(base_tabla)
        texto = self.llamar("leer", path=RECURSO, id=codigo, tabla=tabla)
        if f"tabla {tabla} (1 fila" in texto:
            registro = _unico(self.workspace.crudo(tabla))
            if registro is None:
                raise ErrorPrueba(f"'{codigo}' no se leyó como un registro (objeto JSON).")
            cod = registro.get(_clave(registro, "codigo", "Codigo"))
            if cod is None or _normal(cod) != _normal(codigo):
                raise ErrorPrueba(
                    f"Pedí el cliente '{codigo}' y Finnegans devolvió el código {cod!r}."
                )
            return registro, tabla
        if texto.startswith(_NO_EXISTE):
            if puede_no_existir:
                return None, tabla
            raise ErrorPrueba(f"El cliente '{codigo}' no existe en Finnegans.")
        raise ErrorPrueba(
            f"No pude confirmar la lectura del cliente '{codigo}': la respuesta no es un "
            "registro cargado ni el aviso de que no existe. No lo tomo como 'no existe'."
        )

    def leer_prueba(self) -> dict:
        registro, tabla = self.leer_registro(CODIGO_PRUEBA, TABLA_PRUEBA)
        self.tabla_prueba = tabla
        return registro

    def restos(self) -> list[str]:
        """Codigos ZZ-PRUEBA-MCP que hay hoy: en cliente/list y por id (solo lectura)."""
        tabla = self._tabla_nueva(TABLA_LISTA)
        texto = self.llamar("leer", path=f"{RECURSO}/list", tabla=tabla)
        if f"tabla {tabla} (" not in texto:
            raise ErrorPrueba(
                "No pude cargar cliente/list (la respuesta no confirma la carga): no puedo "
                "saber si quedan registros de prueba."
            )
        sql = (f"SELECT Codigo FROM {tabla} "
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
        # Por si /list no muestra los inactivos: tambien se pregunta por el id directo.
        directo, _ = self.leer_registro(CODIGO_PRUEBA, TABLA_VERIFICACION, puede_no_existir=True)
        if directo is not None and CODIGO_PRUEBA not in codigos:
            codigos.append(CODIGO_PRUEBA)
        return codigos

    def leer_plantilla(self, codigo: str) -> dict:
        registro, _ = self.leer_registro(codigo, TABLA_PLANTILLA)
        return registro

    def verificar_plantilla(self, foto: dict) -> None:
        """La plantilla tiene que seguir igual que antes del alta."""
        try:
            ahora, _ = self.leer_registro(self.plantilla, TABLA_PLANTILLA, puede_no_existir=True)
        except ErrorPrueba:
            self.no_borrar = True
            raise
        if ahora is None:
            self.no_borrar = True
            raise ErrorPrueba(
                f"La plantilla '{self.plantilla}' YA NO EXISTE con su código. Revisá a mano, "
                f"en Finnegans, el cliente '{self.plantilla}' y el cliente '{CODIGO_PRUEBA}' "
                "(el alta podría haber pisado la plantilla). No se borró nada."
            )
        if ahora != foto:
            raise ErrorPrueba(
                f"La plantilla '{self.plantilla}' CAMBIÓ después de la prueba (campos: "
                f"{_claves_distintas(foto, ahora)}). Revisala a mano en Finnegans."
            )

    # -- corrida ----------------------------------------------------------------

    def correr(self, plantilla: str) -> None:
        if plantilla.startswith(PREFIJO):
            raise ErrorPrueba(f"La plantilla no puede ser un {PREFIJO}*: elegí un cliente real.")
        self.plantilla = plantilla
        try:
            self._correr(plantilla)
        except BaseException:
            self._limpiar_tras_fallo()
            raise

    def _correr(self, plantilla: str) -> None:
        # Primero todo lo que solo lee: si algo no cierra, no se escribio nada.
        self.titulo("Buscar restos de corridas anteriores (cliente/list y por id)")
        restos = self.restos()
        self.salida(f"Restos encontrados: {restos or 'ninguno'}")

        self.titulo(f"Leer la plantilla '{plantilla}' (solo lectura) y ver el alta de cliente")
        molde = self.leer_plantilla(plantilla)
        foto = copy.deepcopy(molde)
        ver = self.llamar("ver_endpoint", path=RECURSO, metodo="POST")
        flag = campo_activo(molde, ver)
        requeridos = campos_requeridos(ver)
        alta, sacadas = armar_alta(molde, flag, requeridos, self.copiar_resto)
        self.salida(f"Campos requeridos del swagger: {requeridos or '(no pude leerlos)'}")
        self.salida(f"Claves de identidad sacadas del alta: {sacadas or 'ninguna'}")
        self.salida(f"Campo de estado: {flag} = {alta[flag]!r} (plantilla: {molde.get(flag)!r})")
        unicas = claves_unicas(alta)
        if unicas:
            self.salida(f"Campos que parecen únicos y viajarían en el alta: {unicas}")
            if not self.permitir_campos_unicos:
                raise ErrorPrueba(
                    f"El alta copiaría campos que suelen ser únicos ({', '.join(unicas)}) y "
                    "Finnegans podría rechazarla o duplicarlos. No se escribió nada. Elegí "
                    "otra plantilla, o pasá --permitir-copiar-campos-unicos si no importa."
                )
        clave_nombre = _clave(alta, "nombre", "Nombre")

        if restos:
            self.titulo("Borrar restos")
            for codigo in restos:
                self.escribir("DELETE", id=codigo)

        self.titulo(f"Alta (POST) de {CODIGO_PRUEBA}, inactivo")
        self.pendiente_de_borrar = True
        self.escribir("POST", body=alta)

        self.titulo("Verificar el alta: código, inactivo y plantilla intacta")
        creado = self.leer_prueba()
        if not _esta_inactivo(creado, flag):
            raise ErrorPrueba(
                f"El alta quedó ACTIVA o sin el campo {flag} (vale "
                f"{creado.get(_clave(creado, flag.lower(), flag), '<falta>')!r}): se aborta y "
                "se intenta borrar."
            )
        self.verificar_plantilla(foto)

        self.titulo("Editar con PUT base + cambios")
        texto = self.escribir("PUT", id=CODIGO_PRUEBA, base=self.tabla_prueba,
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
        quedo, _ = self.leer_registro(CODIGO_PRUEBA, TABLA_VERIFICACION, puede_no_existir=True)
        if quedo is not None:
            raise ErrorPrueba(f"{CODIGO_PRUEBA} sigue existiendo después del DELETE.")

        self.titulo("Verificar que no quedó nada en cliente/list y que la plantilla sigue igual")
        quedan = self.restos()
        if quedan:
            raise ErrorPrueba(f"Quedaron registros de prueba: {quedan}")
        self.verificar_plantilla(foto)
        self.salida(f"\nTodo en orden: no queda ningún {PREFIJO}* y la plantilla no cambió.")

    def _limpiar_tras_fallo(self) -> None:
        """Si la prueba se corto con el registro creado, intenta borrarlo (solo ZZ-PRUEBA-MCP)."""
        if not self.pendiente_de_borrar:
            return
        if self.no_borrar:
            self.salida(
                f"\n--- La prueba se cortó y NO borro nada automáticamente: la plantilla "
                f"'{self.plantilla}' pudo haber sido afectada. Revisá a mano en Finnegans "
                f"los clientes '{self.plantilla}' y '{CODIGO_PRUEBA}'. ---"
            )
            return
        self.salida(f"\n--- La prueba se cortó: intento borrar {CODIGO_PRUEBA} ---")
        try:
            self.escribir("DELETE", id=CODIGO_PRUEBA)
            self.pendiente_de_borrar = False
        except Exception as e:  # noqa: BLE001
            self.salida(
                f"No pude borrar {CODIGO_PRUEBA} ({e}). Revisalo y borralo a mano en "
                f"Finnegans, y revisá también la plantilla '{self.plantilla}'."
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
                   help="código de un cliente existente, de BAJO VALOR (solo se lee), del "
                        "que se copian los campos obligatorios del alta")
    p.add_argument("--permitir-copiar-campos-unicos", action="store_true",
                   help="permite que el alta copie campos que suelen ser únicos (CUIT, "
                        "documento, email...); sin esto la prueba aborta antes de escribir")
    p.add_argument("--copiar-resto-de-la-plantilla", action="store_true",
                   help="si el alta con solo los campos requeridos es rechazada: copia toda "
                        "la plantilla (siempre sin ids ni guids)")
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
        Prueba(
            server, workspace, salida,
            permitir_campos_unicos=args.permitir_copiar_campos_unicos,
            copiar_resto=args.copiar_resto_de_la_plantilla,
        ).correr(plantilla)
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
