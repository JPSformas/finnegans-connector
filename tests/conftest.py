"""Fixtures compartidos de la suite."""


import pytest

from finnegans_core.catalogo.swagger import limpiar_caches


@pytest.fixture(autouse=True)
def _limpiar_caches_swagger():
    """Los caches del swagger son por proceso: cada test arranca limpio."""
    limpiar_caches()
    yield
    limpiar_caches()
