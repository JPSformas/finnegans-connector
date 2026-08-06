import unittest
from finnegans import swagger_catalog as sc


class TestCargarSpec(unittest.TestCase):
    def setUp(self):
        sc._SPEC_CACHE.clear()
        self._calls = []

    def _fake_fetch(self, url, key, timeout=60):
        self._calls.append((url, key))
        return {"swagger": "2.0", "paths": {}}

    def test_cachea_tras_primera_carga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        a = sc.cargar_spec("http://x/swaggerGlobal", "k")
        b = sc.cargar_spec("http://x/swaggerGlobal", "k")
        self.assertIs(a, b)
        self.assertEqual(len(self._calls), 1)  # una sola llamada de red

    def test_force_recarga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        sc.cargar_spec("http://x/swaggerGlobal", "k")
        sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)
        self.assertEqual(len(self._calls), 2)

    def test_error_de_red_es_swaggererror(self):
        def boom(url, key, timeout=60):
            raise OSError("sin red")
        sc._fetch_spec = boom  # type: ignore
        with self.assertRaises(sc.SwaggerError):
            sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)


if __name__ == "__main__":
    unittest.main()
