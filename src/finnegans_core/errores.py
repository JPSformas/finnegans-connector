"""Traduccion de errores de la API de Finnegans a mensajes accionables.

El cliente HTTP arma mensajes tecnicos ("Error en GET x (HTTP 405): {...}").
Un lider no tecnico no puede hacer nada con eso, asi que aca se convierten en
una instruccion concreta: que endpoint usar en su lugar, que parametro falta,
o a quien avisarle. Solo libreria estandar.
"""
from __future__ import annotations

import re

# Cuanto detalle crudo se conserva para IT cuando el error no se reconoce.
_DETALLE_MAX = 300


def _recurso(api_id: str) -> str:
    """Nombre del recurso sin el sufijo de operacion: 'x/list' -> 'x'."""
    limpio = (api_id or "").strip("/")
    return re.sub(r"/list$", "", limpio, flags=re.IGNORECASE)


def _codigo_http(mensaje: str) -> int | None:
    m = re.search(r"HTTP (\d{3})", mensaje or "")
    return int(m.group(1)) if m else None


def _metodo(mensaje: str) -> str | None:
    """Metodo HTTP del mensaje del cliente ('Error en PUT cliente (HTTP 500): ...')."""
    m = re.match(r"\s*Error en ([A-Za-z]+) ", mensaje or "")
    return m.group(1).upper() if m else None


def _detalle_api(mensaje: str) -> str:
    """Lo que contesto la API, despues de '(HTTP nnn):'. El mensaje ya viene redactado."""
    m = re.search(r"\(HTTP \d{3}\):\s*(.*)", mensaje or "", flags=re.DOTALL)
    if not m:
        return ""
    detalle = " ".join(m.group(1).split())
    if len(detalle) > _DETALLE_MAX:
        detalle = detalle[:_DETALLE_MAX] + "…"
    return detalle


def traducir_error(api_id: str, mensaje: str, id: str | None = None) -> str:
    """Convierte el error crudo de Finnegans en una indicacion de que hacer.

    Args:
        api_id: endpoint consultado, como lo escribio el agente ('cliente/list').
        mensaje: texto de la FinnegansError.
        id: codigo pedido en el path, si habia.
    """
    msg = mensaje or ""
    bajo = msg.lower()
    recurso = _recurso(api_id) or "el recurso"

    # El nombre del recurso no existe: casi siempre esta escrito distinto.
    if "no se pudo encontrar la api" in bajo:
        return (
            f"No existe una API llamada '{recurso}' en Finnegans. Lo mas probable es "
            f"que se escriba distinto: usa buscar_endpoint para dar con el nombre correcto."
        )

    # Caso mas comun: pedir el listado de un documento en vez de un maestro.
    # Finnegans no expone /list para transacciones; se consultan por reporte.
    # La API lo dice de dos formas distintas segun el recurso.
    if ("no se puede hacer list sobre una transaccion" in bajo
            or "esta api no soporta list" in bajo):
        if "sobre una transaccion" in bajo:
            encabezado = (
                f"'{recurso}' es una transaccion (un documento), no un maestro: "
                f"no tiene listado propio."
            )
        else:
            encabezado = f"'{recurso}' no tiene listado propio en la API."
        return (
            f"{encabezado}\n"
            f"Para ver los documentos de un periodo usa el reporte "
            f"'reports/DETALLETRANSACCIONES' con el parametro PARAM_Categoria "
            f"(y para acotar, PARAM_Fechadesde y PARAM_Fechahasta).\n"
            f"Los valores validos de PARAM_Categoria salen de "
            f"'reports/CATEGORIASDOCUMENTOSAPI'.\n"
            f"Con el codigo de un documento ya en mano, '{recurso}/CODIGO' devuelve "
            f"el detalle completo."
        )

    if "id missing" in bajo:
        return (
            f"El endpoint '{recurso}' necesita el codigo del registro "
            f"(ej. '{recurso}/CODIGO'). Si lo que buscas es la lista completa, "
            f"usa '{recurso}/list'."
        )

    if "no se pudo conectar" in bajo:
        return (
            "No pude conectarme a Finnegans. Puede ser la conexion a internet o que "
            "el servicio este momentaneamente caido. Volve a intentar en unos minutos."
        )

    codigo = _codigo_http(msg)
    metodo = _metodo(msg)
    es_escritura = metodo in {"POST", "PUT", "PATCH", "DELETE"}

    if codigo == 404:
        donde = f"'{recurso}/{id}'" if id else f"'{recurso}'"
        return (
            f"No existe {donde} en Finnegans. Revisa que el codigo este bien escrito; "
            f"si no lo sabes de memoria, buscalo primero en '{recurso}/list'."
        )

    if codigo == 403 and es_escritura:
        # Las credenciales sirven (la lectura del token anduvo): lo que falta es permiso.
        return (
            f"Finnegans no le da permiso a este conector para hacer {metodo} sobre "
            f"'{recurso}': las credenciales funcionan, pero al usuario de la API le falta "
            f"el permiso para esa operacion. Esto no se arregla desde la conversacion: "
            f"avisale a IT que lo habilite en Finnegans."
        )

    if codigo in (401, 403):
        return (
            "Finnegans rechazo las credenciales del conector. Esto no se arregla desde "
            "la conversacion: revisa el Client ID de Finnegans y el Client secret de "
            "Finnegans en la configuracion de la extension en Claude Desktop (o avisale "
            "a IT)."
        )

    if codigo == 500:
        salida = (
            f"Finnegans no pudo procesar la operacion sobre '{recurso}'. Casi siempre "
            f"es un parametro obligatorio que falta o que viene con otro formato. "
            f"Usa ver_endpoint('{recurso}') para ver cuales pide."
        )
        detalle = _detalle_api(msg) if metodo and metodo != "GET" else ""
        if detalle:
            # En una escritura, el motivo del rechazo lo da la API (p. ej. IIBB mixto).
            salida += f"\nLa API respondio: {detalle}"
        return salida

    salida = f"No pude completar la operacion sobre '{recurso}'."
    if msg:
        salida += f"\nDetalle tecnico (para IT): {msg[:_DETALLE_MAX]}"
    return salida
