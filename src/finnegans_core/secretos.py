"""Redaccion de secretos en cualquier texto que pueda llegar al usuario.

El token se pide con las credenciales en el query string, asi que sin esto la
URL completa termina en los mensajes de error, en el log de la instalacion y en
cualquier traceback que el usuario reenvie. Solo libreria estandar.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import quote, quote_plus

MASCARA = "***"


class Redactor:
    """Reemplaza por *** cada valor secreto conocido, el mas largo primero."""

    def __init__(self, valores: Iterable[str] = ()) -> None:
        self._valores: set[str] = set()
        for v in valores:
            self.agregar(v)

    def agregar(self, valor: str) -> None:
        """Registra el valor y sus formas codificadas para URL.

        Las credenciales viajan en el query string, asi que un error que repita
        la URL las muestra con porcentaje (a+b/c -> a%2Bb%2Fc).
        """
        if not valor:
            return
        valor = str(valor)
        self._valores.add(valor)
        for variante in (quote(valor, safe=""), quote_plus(valor), quote(valor)):
            if variante != valor:
                self._valores.add(variante)

    def limpiar(self, texto: object) -> str:
        salida = str(texto)
        for valor in sorted(self._valores, key=len, reverse=True):
            salida = salida.replace(valor, MASCARA)
        return salida
