"""Guia de negocio: temas en Markdown, uno por archivo, empaquetados con el modulo."""

from importlib import resources

_DESCRIPCIONES: dict[str, str] = {
    "sucursales": "Sucursales, unidades de negocio y cuándo preguntar",
    "iibb": "Situaciones de IIBB (ControlImpositivo1) y sus reglas",
    "rutas": "Convención de rutas y cómo encontrar el endpoint",
    "tipos": "Tipos de endpoint: Viewer, EntidadVO y otros",
    "escrituras": "PUT de registro completo, diff y advertencias",
    "clientes": "cliente/list, formatos de código y datos sucios",
    "parametros": "Parámetros de reportes: fechas relativas, arbol(), DEALS",
}

TEMAS: tuple[str, ...] = tuple(_DESCRIPCIONES)


def _lista() -> str:
    lineas = [f"- {t}: {d}" for t, d in _DESCRIPCIONES.items()]
    return "Temas disponibles (pedí uno con guia(tema)):\n" + "\n".join(lineas)


def guia(tema: str | None = None) -> str:
    """Devuelve un tema de la guia, o la lista de temas si no se indica o no existe."""
    if tema is None or not tema.strip():
        return _lista()
    clave = tema.strip().lower()
    if clave not in TEMAS:
        return f'No existe el tema "{tema}".\n\n{_lista()}'
    return (resources.files(__package__) / f"{clave}.md").read_text(encoding="utf-8")
