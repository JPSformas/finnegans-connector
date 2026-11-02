"""Busqueda unificada de endpoints: swagger (fuente de verdad) + MCP de docs.

El swagger dice que endpoints existen y de que tipo son; el MCP de documentacion
aporta una segunda opinion semantica. Si las dos coinciden, la confianza es alta;
si no, o si el resultado es ambiguo, se deja una nota para que el agente le
pregunte al usuario en lugar de adivinar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import anyio
import anyio.to_thread

from .docs_mcp import DocsMcp
from .swagger import SwaggerCatalog, TipoEndpoint

_PREGUNTAR = "preguntale al usuario"
_METODOS_HTTP = {"get", "post", "put", "delete", "patch"}


@dataclass
class FilaBusqueda:
    path: str
    metodos: list[str]
    tipo: TipoEndpoint
    resumen: str
    fuentes: list[str] = field(default_factory=list)  # "swagger" y/o "docs"
    # False si la documentacion lo sugiere pero el swagger no tiene ese path.
    en_swagger: bool = True


@dataclass
class ResultadoBusqueda:
    filas: list[FilaBusqueda] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


class _IndicePaths:
    """Traduce un id del MCP de docs ('ACOrdenesCompraDetalle') a un path del swagger."""

    def __init__(self, swagger: SwaggerCatalog) -> None:
        self._completos: dict[str, str] = {}
        self._ultimos: dict[str, str] = {}
        self._metodos: dict[str, list[str]] = {}
        self.cargado = False
        try:
            paths = swagger.spec().get("paths") or {}
        except Exception:  # sin spec no hay nada que cruzar: se usa el id tal cual
            paths = {}
        self.cargado = bool(paths)
        for path, ops in paths.items():
            clave = _clave(path)
            self._completos.setdefault(clave, path)
            self._ultimos.setdefault(clave.rsplit("/", 1)[-1], path)
            if isinstance(ops, dict):
                self._metodos[path] = [m.upper() for m in ops if m.lower() in _METODOS_HTTP]

    def resolver(self, ident: str) -> str:
        clave = _clave(ident)
        return self._completos.get(clave) or self._ultimos.get(clave) or ident

    def existe(self, path: str) -> bool:
        """True si el path (ya resuelto) esta en el swagger, sin importar mayusculas."""
        return _clave(path) in self._completos

    def metodos(self, path: str) -> list[str]:
        return list(self._metodos.get(path, []))


def _clave(path: str) -> str:
    return path.strip("/").lower()


async def buscar_endpoint(
    consulta: str,
    swagger: SwaggerCatalog,
    docs: DocsMcp | None,
    limite: int = 8,
) -> ResultadoBusqueda:
    """Busca en el swagger y en el MCP de docs a la vez y une los resultados."""
    swagger_res: list = []
    swagger_err: list[Exception] = []
    docs_res: list[dict] = []
    docs_ok = False

    async def _swagger() -> None:
        # El swagger usa un cliente HTTP bloqueante: va a un hilo.
        try:
            swagger_res.extend(await anyio.to_thread.run_sync(swagger.buscar, consulta, limite))
        except Exception as e:
            swagger_err.append(e)

    async def _docs() -> None:
        nonlocal docs_ok
        if docs is None:
            return
        try:
            docs_res.extend(await docs.buscar(consulta))
            docs_ok = True
        except Exception:
            docs_ok = False  # se informa con una nota; el swagger alcanza

    async with anyio.create_task_group() as tg:
        tg.start_soon(_swagger)
        tg.start_soon(_docs)
    if swagger_err:
        raise swagger_err[0]

    indice = _IndicePaths(swagger)
    docs_paths = [indice.resolver(d["path"]) for d in docs_res]
    claves_docs = {_clave(p) for p in docs_paths}

    filas: list[FilaBusqueda] = []
    fuera_del_swagger: list[str] = []
    vistos: set[str] = set()
    for c in swagger_res:
        vistos.add(_clave(c.path))
        fuentes = ["swagger"] + (["docs"] if _clave(c.path) in claves_docs else [])
        filas.append(FilaBusqueda(c.path, list(c.metodos), c.tipo, c.resumen, fuentes))
    for path, d in zip(docs_paths, docs_res):
        if _clave(path) in vistos:
            continue
        vistos.add(_clave(path))
        # Sin spec cargado no se puede saber; el swagger es la fuente de verdad.
        en_swagger = not indice.cargado or indice.existe(path)
        if not en_swagger:
            fuera_del_swagger.append(path)
        filas.append(FilaBusqueda(
            path=path,
            metodos=indice.metodos(path),
            tipo=swagger.tipo(path),
            resumen=d.get("resumen", ""),
            fuentes=["docs"],
            en_swagger=en_swagger,
        ))

    notas: list[str] = []
    if not docs_ok:
        notas.append(
            "resultados solo con el swagger: la documentación no está disponible ahora; "
            f"si dudás entre opciones, {_PREGUNTAR}"
        )
    elif docs_paths and _clave(docs_paths[0]) not in {_clave(c.path) for c in swagger_res}:
        notas.append(
            f"las fuentes no coinciden: la documentación sugiere {docs_paths[0]} "
            f"y el swagger propone otros endpoints; para saber cuál corresponde, {_PREGUNTAR}"
        )
    if fuera_del_swagger:
        notas.append(
            f"la documentación sugiere {', '.join(fuera_del_swagger)} pero no está en el "
            "swagger: puede que no exista o que se llame distinto; antes de usarlo, "
            f"{_PREGUNTAR}"
        )
    if len(swagger_res) >= 2 and math.isclose(swagger_res[0].puntaje, swagger_res[1].puntaje):
        notas.append(
            f"hay un empate entre {swagger_res[0].path} y {swagger_res[1].path}; "
            f"para saber cuál quiere, {_PREGUNTAR}"
        )
    if swagger_res and max(c.cobertura for c in swagger_res) < 1:
        notas.append(
            "coincidencia parcial: ningún endpoint cubre todas las palabras de la consulta; "
            f"para saber qué necesita exactamente, {_PREGUNTAR}"
        )
    return ResultadoBusqueda(filas=filas, notas=notas)


def formatear_busqueda(r: ResultadoBusqueda) -> str:
    """Una linea por endpoint y, si hay, las notas debajo."""
    lineas: list[str] = []
    for f in r.filas:
        partes = ["-"]
        if f.metodos:
            partes.append(",".join(f.metodos))
        partes.append(f.path)
        partes.append(f"[{f.tipo}]")
        if f.resumen:
            partes.append(f.resumen)
        partes.append(f"({'+'.join(f.fuentes)})")
        if not f.en_swagger:
            partes.append("(no está en el swagger)")
        lineas.append(" ".join(partes))
    if not lineas:
        lineas.append("No encontré endpoints para esa consulta.")
    if r.notas:
        lineas.append("Notas:")
        lineas.extend(f"- {n}" for n in r.notas)
    return "\n".join(lineas)
