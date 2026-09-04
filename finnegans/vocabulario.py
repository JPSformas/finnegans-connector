"""Vocabulario de negocio para la busqueda de endpoints.

Un lider no escribe como se llaman los endpoints de Finnegans. Escribe
"tesoreria", "caja" o "cheque" en singular, y la API se llama
movimientoFondos, ordenPago o ApiSituacionCheques. Este modulo cierra esa
distancia en tres frentes:

  - acentos: "tesoreria" se escribe con tilde, y el tokenizador partia la
    palabra en dos donde estaba el acento.
  - plurales: se generan las formas singular/plural para que la consulta y
    el nombre del endpoint se encuentren.
  - sinonimos: palabras de negocio que no aparecen en ningun nombre de
    endpoint y hay que traducir al vocabulario de la API.

Solo libreria estandar.
"""
from __future__ import annotations

import unicodedata

# La enie es una letra propia, no una 'n' con acento: normalizarla cambiaria
# la palabra ("ano" no es "año").
_CONSERVAR = {"ñ", "Ñ"}

_VOCALES = "aeiou"

# Por debajo de este largo no se toca el plural: 'mas' o 'dos' perderian la s
# y colisionarian con medio catalogo.
_MIN_PLURAL = 4

# Palabra de negocio -> palabras que si aparecen en los nombres de la API.
# Cada destino esta verificado contra el spec real: un destino que no exista
# no matchea nunca y el error pasa desapercibido (ver test_vocabulario).
SINONIMOS: dict[str, tuple[str, ...]] = {
    # Tesoreria: ninguna de estas dos palabras aparece en el catalogo.
    # A proposito apuntan a un solo destino: mapear una palabra a media docena
    # de familias genera empates de score que terminan empujando afuera del
    # limite justo al endpoint mas central.
    "tesoreria": ("fondos",),
    "caja": ("fondos",),
    # 'banco' y 'bancario' son la misma idea pero distinta palabra.
    "banco": ("bancario",),
    "bancario": ("banco",),
    # Verbos: el lider pide "cobrar", la API dice "cobranza".
    "cobrar": ("cobranza", "cobro"),
    "pagar": ("pago",),
    "vender": ("venta",),
    "comprar": ("compra",),
    # /remito no existe (la API responde 501): son despacho y recepcion.
    "remito": ("despacho", "recepcion"),
    "inventario": ("stock",),
    "contabilidad": ("asiento", "cuenta"),
    "contable": ("asiento", "cuenta"),
}


def sin_acentos(texto: str | None) -> str:
    """Saca los acentos conservando la enie y las mayusculas.

    Preserva el caso a proposito: quien tokeniza necesita los limites de
    camelCase ('movimientoFondos') y lowercasear antes los borraria.
    """
    if not texto:
        return ""
    salida = []
    for ch in texto:
        if ch in _CONSERVAR:
            salida.append(ch)
            continue
        descompuesto = unicodedata.normalize("NFD", ch)
        salida.append("".join(c for c in descompuesto if not unicodedata.combining(c)))
    return "".join(salida)


def normalizar(texto: str | None) -> str:
    """Minusculas y sin acentos, conservando la enie."""
    return sin_acentos(texto).lower()


def variantes(palabra: str) -> set[str]:
    """Formas de la palabra que deben considerarse la misma.

    No intenta ser un lematizador: genera el singular probable para que la
    consulta y el nombre del endpoint se crucen aunque uno este en plural.
    """
    p = normalizar(palabra)
    if not p:
        return set()
    formas = {p}
    if len(p) >= _MIN_PLURAL and p.endswith("s"):
        # plural en vocal: cheques -> cheque, facturas -> factura
        formas.add(p[:-1])
        # plural en consonante: proveedores -> proveedor, ordenes -> orden
        if p.endswith("es") and p[-3] not in _VOCALES:
            formas.add(p[:-2])
    return formas


def sinonimos_de(palabra: str) -> tuple[str, ...]:
    """Palabras del vocabulario de la API para una palabra de negocio."""
    return SINONIMOS.get(normalizar(palabra), ())
