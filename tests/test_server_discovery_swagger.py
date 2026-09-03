import unittest
import server
from finnegans import swagger_catalog as sc
from tests.test_swagger_catalog import SPEC


class TestServerDiscovery(unittest.TestCase):
    def setUp(self):
        sc._SPEC_CACHE.clear()
        self._orig_fetch_spec = sc._fetch_spec
        sc._fetch_spec = lambda url, key, timeout=60: SPEC  # type: ignore
        # asegurar que require_swagger_config no falle
        s = server.get_settings()
        self._orig_swagger_key = s.swagger_key
        s.swagger_key = "k"

    def tearDown(self):
        sc._fetch_spec = self._orig_fetch_spec
        sc._SPEC_CACHE.clear()
        server.get_settings().swagger_key = self._orig_swagger_key

    def test_buscar_api_lista_paths_reales(self):
        out = server.buscar_api("cliente")
        self.assertIn("/cliente/list", out)
        self.assertIn("/cliente/{codigo}", out)

    def test_ver_api_muestra_operaciones_y_params(self):
        out = server.ver_api("cliente")
        self.assertIn("/cliente/list", out)
        self.assertIn("POST", out)
        self.assertIn("codigo", out)


if __name__ == "__main__":
    unittest.main()
