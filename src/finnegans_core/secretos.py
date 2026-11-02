"""Redaccion de secretos en cualquier texto que pueda llegar al usuario.

El token se pide con las credenciales en el query string, asi que sin esto la
URL completa termina en los mensajes de error, en el log de la instalacion y en
cualquier traceback que el usuario reenvie. Solo libreria estandar.
"""
from __future__ import annotations

from typing import Iterable

MASCARA = "***"


class Redactor:
    """Reemplaza por *** cada valor secreto conocido, el mas largo primero."""

    def __init__(self, valores: Iterable[str] = ()) -> None:
        self._valores: set[str] = set()
        for v in valores:
            self.agregar(v)

    def agregar(self, valor: str) -> None:
        if valor:
            self._valores.add(str(valor))

    def limpiar(self, texto: object) -> str:
        salida = str(texto)
        for valor in sorted(self._valores, key=len, reverse=True):
            salida = salida.replace(valor, MASCARA)
        return salida
