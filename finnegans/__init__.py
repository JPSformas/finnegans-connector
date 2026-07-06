"""Conector para la API de Finnegans (Teamplace / F3).

Expone un cliente seguro que maneja la autenticacion por
client_credentials y ofrece metodos de lectura para las areas del
negocio. Los secretos se leen desde variables de entorno / .env y
nunca se escriben en logs.
"""
from .client import FinnegansClient, FinnegansError, FinnegansAuthError

__all__ = ["FinnegansClient", "FinnegansError", "FinnegansAuthError"]
