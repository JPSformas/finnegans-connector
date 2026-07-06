"""Conector / Agente para la API de Finnegans (Teamplace / F3)."""
from .client import FinnegansClient, FinnegansAuthError, FinnegansError
from .discovery import DiscoveryError, get_api, search_apis
from .validator import ChangeStore, ValidationError

__all__ = [
    "FinnegansClient",
    "FinnegansError",
    "FinnegansAuthError",
    "DiscoveryError",
    "ValidationError",
    "ChangeStore",
    "search_apis",
    "get_api",
]
